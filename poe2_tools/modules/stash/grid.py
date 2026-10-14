#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
背包网格识别（OpenCV，仓库打开时背包网格显示在屏幕右下区域）。

原理：网格边框是贯通整个网格的长直线，物品内容边缘短——
Canny 边缘 + HoughLinesP 长直线过滤（minLineLength 按比例）→
位置聚类 → 晶格拟合（间距一致的最长连续线列，跳过物品噪声线）。

实测（2560×1440）：格距约 70px，12 列 × 5 行；
拟合原点允许 ≈10px 偏差（格子半宽 35，点击不受影响）。

纯逻辑（聚类/晶格拟合）与图像管线分离，可单测。
"""

from __future__ import annotations

from dataclasses import dataclass

from poe2_tools.config.settings import Point

# 网格搜索区域（占客户区比例）：仓库打开时背包网格在右下
_SEARCH_X0_RATIO = 0.55
_SEARCH_Y0_RATIO = 0.42
_SEARCH_Y1_RATIO = 0.95

# Canny / Hough 参数（2560×1440 实测调定）
_CANNY_LO = 30
_CANNY_HI = 80
_HOUGH_THRESHOLD = 150
_HOUGH_MIN_LEN_H_RATIO = 0.12  # 最小线长 = 屏高比例（5 行网格线长约 0.24h）
_HOUGH_MAX_GAP = 8

# 位置聚类：距离 ≤ 该值视为同一条线（边框厚度/重检）
_CLUSTER_GAP = 6
# 格距合理范围（像素）：低于下限必是噪声，高于上限不是格子
_PITCH_MIN = 40
_PITCH_MAX = 120
# 晶格拟合容差：相邻线距允许偏离名义格距（边框厚度 + 检测抖动）
_PITCH_TOL = 12
# 横纵格距一致性校验（方格）：超过则判定识别失败
_PITCH_MATCH_TOL = 3.0
# 行列数合理范围（识别结果 sanity check）
_MIN_LINES = 4
_MAX_CELLS = 16


@dataclass
class BagGrid:
    """背包网格：第 1 格中心（客户区坐标）+ 格距 + 行列数。"""

    origin: Point
    cell: float
    rows: int
    cols: int


# ============================================================
# 纯逻辑：线位置聚类与晶格拟合（可单测）
# ============================================================
def cluster_positions(positions: list[int], gap: int = _CLUSTER_GAP) -> list[int]:
    """把相近的线位置聚类为一条（取均值）；输入无需有序。"""
    out: list[list[int]] = []
    for pos in sorted(positions):
        if out and pos - out[-1][-1] <= gap:
            out[-1].append(pos)
        else:
            out.append([pos])
    return [round(sum(group) / len(group)) for group in out]


def fit_axis(lines: list[int]) -> list[int] | None:
    """
    在一组线位置里找间距一致的最长连续线列（晶格拟合），返回该线列。

    不做全局格距估计（噪声差值会污染中位数/投票）：枚举起点与第二根线
    确定初始格距，之后贪心扩展——跳过过近的噪声线，窗口内取离晶格点
    最近的线，动态格距 = run 内差值均值。线数 < _MIN_LINES 返回 None。
    """
    best: list[int] = []
    for start in range(len(lines)):
        for second in range(start + 1, len(lines)):
            d0 = lines[second] - lines[start]
            if not (_PITCH_MIN <= d0 <= _PITCH_MAX):
                continue
            run = [lines[start], lines[second]]
            cursor = second
            while True:
                pitch = (run[-1] - run[0]) / (len(run) - 1)
                center = run[-1] + pitch
                lo, hi = center - _PITCH_TOL, center + _PITCH_TOL
                # 窗口内可能有多条线（噪声贴线）：取离晶格点最近的一条
                nxt, best_dist = None, _PITCH_TOL + 1.0
                for i in range(cursor + 1, len(lines)):
                    if lines[i] < lo:
                        continue  # 过近：物品内容等噪声线，跳过
                    if lines[i] > hi:
                        break
                    dist = abs(lines[i] - center)
                    if dist < best_dist:
                        nxt, best_dist = i, dist
                if nxt is None:
                    break
                run.append(lines[nxt])
                cursor = nxt
            if len(run) > len(best):
                best = run
    return best if len(best) >= _MIN_LINES else None


def covered_window(
    h_run: list[int], v_spans: list[tuple[int, int]], min_cover: float = 0.8
) -> list[int] | None:
    """
    用竖线的 y 覆盖范围裁剪水平线列，返回背包网格实际占用的水平线窗口。

    水平线列可能向上（装备栏框线）或向下（金币栏/面板装饰）串线；
    背包网格的判据：格子间隔中点被绝大多数竖线穿过（y_min ≤ 中点 ≤ y_max）。
    返回被覆盖的最长连续线列；没有任何间隔被覆盖时返回 None。
    """
    if len(h_run) < 2 or not v_spans:
        return None
    ok = []
    for top, bottom in zip(h_run, h_run[1:]):
        mid = (top + bottom) / 2
        covered = sum(1 for y_min, y_max in v_spans if y_min <= mid <= y_max)
        ok.append(covered / len(v_spans) >= min_cover)
    best_start = best_len = 0
    cur_start = cur_len = 0
    for i, good in enumerate(ok):
        if good:
            if cur_len == 0:
                cur_start = i
            cur_len += 1
            if cur_len > best_len:
                best_start, best_len = cur_start, cur_len
        else:
            cur_len = 0
    if best_len == 0:
        return None
    return h_run[best_start: best_start + best_len + 1]


# ============================================================
# 图像管线：截图 → 长直线 → 网格
# ============================================================
def detect_bag_grid(image) -> BagGrid | None:
    """识别背包网格（PIL 图像，客户区整屏截图）；失败返回 None。"""
    import cv2  # noqa: PLC0415 懒导入
    import numpy as np  # noqa: PLC0415 懒导入

    width, height = image.size
    x0 = round(width * _SEARCH_X0_RATIO)
    y0 = round(height * _SEARCH_Y0_RATIO)
    y1 = round(height * _SEARCH_Y1_RATIO)
    region = cv2.cvtColor(np.asarray(image.convert("RGB"))[y0:y1, x0:], cv2.COLOR_RGB2GRAY)

    edges = cv2.Canny(region, _CANNY_LO, _CANNY_HI)
    lines = cv2.HoughLinesP(
        edges, 1, np.pi / 180,
        threshold=_HOUGH_THRESHOLD,
        minLineLength=round(height * _HOUGH_MIN_LEN_H_RATIO),
        maxLineGap=_HOUGH_MAX_GAP,
    )
    if lines is None:
        return None

    vlines: list[tuple[int, int, int]] = []  # (x, y_min, y_max) 客户区坐标
    hlines: list[int] = []  # y（客户区坐标）
    for line in lines.reshape(-1, 4):
        x1, y1, x2, y2 = (int(v) for v in line)
        if abs(x1 - x2) <= 2:
            vlines.append((round((x1 + x2) / 2) + x0, min(y1, y2) + y0, max(y1, y2) + y0))
        elif abs(y1 - y2) <= 2:
            hlines.append(round((y1 + y2) / 2) + y0)

    v_run = fit_axis(cluster_positions([x for x, _, _ in vlines]))
    h_run = fit_axis(cluster_positions(hlines))
    if v_run is None or h_run is None:
        return None
    pitch_v = (v_run[-1] - v_run[0]) / (len(v_run) - 1)

    # 竖线 y 覆盖范围（按 x 聚类合并同名线的分段），用于裁剪水平线列的串线
    v_spans = _merge_v_spans(vlines, v_run)
    h_window = covered_window(h_run, v_spans)
    if h_window is None or len(h_window) < _MIN_LINES:
        return None
    pitch_h = (h_window[-1] - h_window[0]) / (len(h_window) - 1)

    cols, rows = len(v_run) - 1, len(h_window) - 1
    if not (1 <= cols <= _MAX_CELLS and 1 <= rows <= _MAX_CELLS):
        return None
    if abs(pitch_v - pitch_h) > _PITCH_MATCH_TOL:
        return None  # 方格校验：横纵格距不一致说明误识别
    return BagGrid(
        origin=Point(round(v_run[0] + pitch_v / 2), round(h_window[0] + pitch_h / 2)),
        cell=round((pitch_v + pitch_h) / 2, 1),
        rows=rows,
        cols=cols,
    )


def _merge_v_spans(
    vlines: list[tuple[int, int, int]], v_run: list[int]
) -> list[tuple[int, int, int]]:
    """把竖线分段按 x 聚类合并为 (y_min, y_max) 覆盖范围，只保留晶格线列内的。"""
    spans: list[tuple[int, int]] = []
    for x in v_run:
        segs = [(y1, y2) for vx, y1, y2 in vlines if abs(vx - x) <= _CLUSTER_GAP]
        if segs:
            spans.append((min(y1 for y1, _ in segs), max(y2 for _, y2 in segs)))
    return spans
