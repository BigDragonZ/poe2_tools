#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通货市场结果面板的 OCR 文本解析（纯逻辑，可单测）。

输入为 OCR 识别出的文本行列表，输出按面板从上到下顺序排列的挂单：
[{"rank": 1, "ratio": "1:155", "stock": 42}, ...]

容错策略：
- 有效性以「能解析出兑换比例」为准（游戏字体下「库存/Stock」识别不稳定，
  识别不到库存时仍返回比率，stock 为 None）
- 比例与库存常被 OCR 拆成两行（不同列）：库存独立成行时合并到相邻挂单
- 库存特征词允许模糊匹配：中文「库存」直接子串匹配；英文 Stock 接受
  常见 OCR 混淆（5tock / st0ck / st ock 等），归一化后正则匹配
- 比例接受冒号或斜杠分隔（1:155 / 1/155），支持小数
- 库存数字允许千分位逗号；取库存特征词之后的第一个整数
- 所有行都解析不出比例时返回空数组（该方向无可用交易）
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 库存特征：中文「库存」或英文 Stock 的常见 OCR 变体
_STOCK_RE = re.compile(r"库存|[s5]t[o0]ck", re.IGNORECASE)

# 兑换比例：数字 : 数字 或 数字 / 数字（支持小数与千分位）
_RATIO_RE = re.compile(r"(\d[\d,]*(?:\.\d+)?)\s*[:：/]\s*(\d[\d,]*(?:\.\d+)?)")

# 数字（支持千分位逗号/点号与小数，如 624 / 3,359 / 875.556 / 10.40）
_NUM_RE = re.compile(r"\d[\d.,]*")

# 裸数字文本块（整格就是数字，如库存列的 624 / 3,359 / 875.556）
_BARE_NUM_RE = re.compile(r"\d[\d.,]*")

# 行聚合：文本块纵向中心差 ≤ 行高×0.6（至少 6px）视为同一行
_ROW_Y_MIN_TOL = 6.0
_ROW_Y_RATIO = 0.6

# 每个方向最多保留的挂单条数（按面板从上到下取前 N 条）
MAX_RESULTS = 3


@dataclass
class TextBlock:
    """OCR 文本块：文字 + 检测框中心坐标与高度（像素）。"""

    text: str
    cx: float
    cy: float
    h: float


def _normalize(text: str) -> str:
    """归一化：去全部空白（OCR 常在字符间插空格）。"""
    return re.sub(r"\s+", "", text)


def has_stock_feature(line: str) -> bool:
    """判断一行文本是否含库存特征（模糊匹配）。"""
    return bool(_STOCK_RE.search(_normalize(line)))


def _to_number(raw: str) -> int | float:
    """
    解析数字文本：去千分位逗号；单个点号后恰为 3 位数字视为千分位点
    （875.556 → 875556），否则视为小数（10.40 → 10.4）。
    """
    s = raw.replace(",", "")
    if s.count(".") == 1:
        head, tail = s.split(".")
        if len(tail) == 3 and tail.isdigit() and head.isdigit():
            return int(head + tail)
        return float(s)
    if s.count(".") > 1:
        return int(s.replace(".", ""))  # 多点号按千分位处理（1.234.567）
    return int(s)


def _extract(line: str) -> tuple[str | None, int | float | None]:
    """从一行文本提取 (比例, 库存)；各自独立存在或缺失。"""
    norm = _normalize(line)
    ratio: str | None = None
    stock: int | float | None = None
    ratio_match = _RATIO_RE.search(norm)
    if ratio_match is not None:
        ratio = f"{ratio_match.group(1)}:{ratio_match.group(2)}"
    stock_match = _STOCK_RE.search(norm)
    if stock_match is not None:
        tail = _NUM_RE.search(norm[stock_match.end():])
        if tail is not None:
            stock = _to_number(tail.group(0))
    return ratio, stock


def parse_market_line(line: str) -> dict | None:
    """
    解析单行文本为挂单 dict；无法提取比例时返回 None。
    比例统一输出为冒号分隔（"1:155"），无论识别到的是冒号还是斜杠。
    库存识别不到为 None（界面显示 "-"）。
    """
    ratio, stock = _extract(line)
    if ratio is None:
        return None
    return {"ratio": ratio, "stock": stock}


def parse_market_lines(lines: list[str]) -> list[dict]:
    """
    解析 OCR 文本行列表，按从上到下顺序输出挂单列表（rank 从 1 起）。

    OCR 常把同行的比例与库存识别成两个独立文本块（不同列），因此
    「只有库存没有比例」的行会合并到最近一条缺库存的挂单；若它出现在
    任何比例行之前（如表头串行），则暂存给下一条挂单。
    全部行都解析不出比例时返回空数组（该方向无可用交易）。
    最多保留前 MAX_RESULTS 条。
    """
    results: list[dict] = []
    pending_stock: int | None = None
    for line in lines:
        ratio, stock = _extract(line)
        if ratio is not None:
            results.append({
                "rank": len(results) + 1,
                "ratio": ratio,
                "stock": stock if stock is not None else pending_stock,
            })
            pending_stock = None
        elif stock is not None:
            target = next((e for e in reversed(results) if e["stock"] is None), None)
            if target is not None:
                target["stock"] = stock
            else:
                pending_stock = stock
    return results[:MAX_RESULTS]


# ============================================================
# 带坐标文本块解析（行聚合 + 行内配对，主路径）
# ============================================================
def group_rows(blocks: list[TextBlock]) -> list[list[TextBlock]]:
    """把文本块按纵向中心聚成行（从上到下，行内从左到右）。"""
    rows: list[list[TextBlock]] = []
    for block in sorted(blocks, key=lambda b: (b.cy, b.cx)):
        if rows:
            row = rows[-1]
            ref_cy = sum(b.cy for b in row) / len(row)
            ref_h = sum(b.h for b in row) / len(row)
            tol = max(_ROW_Y_MIN_TOL, ref_h * _ROW_Y_RATIO, block.h * _ROW_Y_RATIO)
            if abs(block.cy - ref_cy) <= tol:
                row.append(block)
                continue
        rows.append([block])
    return [sorted(row, key=lambda b: b.cx) for row in rows]


def _bare_number(text: str) -> int | float | None:
    """整格就是数字时返回其值（库存列常见形态），否则 None。"""
    norm = _normalize(text)
    if _BARE_NUM_RE.fullmatch(norm):
        return _to_number(norm)
    return None


def parse_market_blocks(blocks: list[TextBlock]) -> list[dict]:
    """
    按检测框坐标重建表格行并解析挂单（rank 按行从上到下、行内从左到右）。

    行内配对规则：比例与库存可能分列、顺序不定（实测两种都存在）——
    逐格扫描，比例格记下待配对；其后的库存格（「库存/Stock+N」或裸数字）
    补全该挂单；库存格先于比例格出现时暂存，配给本行下一个比例。
    全部行都解析不出比例时返回空数组（该方向无可用交易）。
    最多保留前 MAX_RESULTS 条。
    """
    pairs: list[dict] = []
    for row in group_rows(blocks):
        pending_ratio: str | None = None
        pending_stock: int | float | None = None
        for cell in row:
            ratio, kw_stock = _extract(cell.text)
            bare = _bare_number(cell.text)
            if ratio is not None:
                if pending_ratio is not None:
                    pairs.append({"ratio": pending_ratio, "stock": pending_stock})
                    pending_stock = None
                pending_ratio = ratio
                if kw_stock is not None:
                    pairs.append({"ratio": pending_ratio, "stock": kw_stock})
                    pending_ratio = None
            else:
                num = kw_stock if kw_stock is not None else bare
                if num is None:
                    continue
                if pending_ratio is not None:
                    pairs.append({"ratio": pending_ratio, "stock": num})
                    pending_ratio = None
                else:
                    pending_stock = num
        if pending_ratio is not None:
            pairs.append({"ratio": pending_ratio, "stock": pending_stock})
    return [{"rank": i + 1, **pair} for i, pair in enumerate(pairs[:MAX_RESULTS])]
