#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
仓库界面检测与仓库箱子定位。

- stash_open()：面板右缘采样点亮度判断仓库界面是否打开（开≈40 / 关≈120），
  从 map_vaal 提取为公共实现（2026-10-14）
- find_stash_label()：OCR 文本块里模糊匹配「倉庫」标签（纯逻辑，可单测）。
  实测 RapidOCR 会把「倉庫」误读为「合库/食库」，故按字符集模糊匹配；
  右上角地图面板里也有「倉庫」字样，按区域排除
- locate_stash_chest()：截屏 → OCR → 匹配标签 → 返回箱子点击点
  （标签中心向下偏移，点标签下方箱子本体）
"""

from __future__ import annotations

from poe2_tools.config.settings import Point
from poe2_tools.core import window
from poe2_tools.core.ocr import OcrEngine, TextBlock

# 仓库开启检测：面板右缘采样点（客户区）与亮度阈值（开≈40 / 关≈120）
STASH_PROBE_POINTS = [(850, 300), (850, 600), (850, 950)]
STASH_PROBE_THRESHOLD = 80

# 「倉庫」模糊匹配字符集：OCR 实测误读为「合库」「食库」
_LABEL_FIRST_CHARS = "倉仓合食苍蒼仑侖"
_LABEL_SECOND_CHARS = "庫库"
# 标签文字长度范围（归一化去空白后）
_LABEL_MIN_LEN = 2
_LABEL_MAX_LEN = 3

# 右上角地图面板排除区（占屏比例）：面板里也有「倉庫」字样，不能点
_MAP_PANEL_X_RATIO = 0.60
_MAP_PANEL_Y_RATIO = 0.45

# 点击点 = 标签中心向下偏移（点标签下方箱子本体）：实测标签 h=36 时偏移 42px
_CLICK_OFFSET_H_RATIO = 1.2


def stash_open() -> bool:
    """按面板右缘采样点亮度判断仓库界面是否打开（开≈40 / 关≈120）。"""
    import mss  # noqa: PLC0415 懒导入

    origin = window.client_origin()
    if origin is None:
        return False
    regions = [
        {"left": origin.x + x - 3, "top": origin.y + y - 3, "width": 6, "height": 6}
        for x, y in STASH_PROBE_POINTS
    ]
    with mss.MSS() as sct:
        means = []
        for region in regions:
            shot = sct.grab(region)
            # 用 RGB 三通道求亮度近似（raw 含 Alpha=255 会抬高均值）
            rgb = shot.rgb
            means.append(sum(rgb) / len(rgb))
    return sum(means) / len(means) < STASH_PROBE_THRESHOLD


def screenshot_client():
    """截取 POE2 客户区整屏，返回 PIL Image；窗口未找到返回 None。"""
    import mss  # noqa: PLC0415 懒导入
    from PIL import Image  # noqa: PLC0415 懒导入

    origin = window.client_origin()
    size = window.client_size()
    if origin is None or size is None:
        return None
    with mss.MSS() as sct:
        shot = sct.grab({
            "left": origin.x, "top": origin.y, "width": size.x, "height": size.y,
        })
        return Image.frombytes("RGB", shot.size, shot.rgb)


def _is_stash_label_text(text: str) -> bool:
    """模糊匹配「倉庫」标签文字（容忍 OCR 误读，纯逻辑）。"""
    normalized = "".join(text.split())
    if not (_LABEL_MIN_LEN <= len(normalized) <= _LABEL_MAX_LEN):
        return False
    return (
        any(c in _LABEL_FIRST_CHARS for c in normalized)
        and any(c in _LABEL_SECOND_CHARS for c in normalized)
    )


def find_stash_label(
    blocks: list[TextBlock], width: int, height: int
) -> TextBlock | None:
    """在 OCR 文本块里定位世界中的「倉庫」标签（纯逻辑，可单测）。

    排除右上角地图面板区域（面板里也有「倉庫」字样）；
    多个候选时取文字高度最大的（牌匾标签字大于一般 UI 文本）。
    """
    map_x = width * _MAP_PANEL_X_RATIO
    map_y = height * _MAP_PANEL_Y_RATIO
    candidates = [
        b for b in blocks
        if _is_stash_label_text(b.text) and not (b.cx > map_x and b.cy < map_y)
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda b: b.h)


def chest_click_point(label: TextBlock) -> Point:
    """箱子点击点：标签中心向下偏移（点标签下方箱子本体，纯逻辑）。"""
    return Point(round(label.cx), round(label.cy + label.h * _CLICK_OFFSET_H_RATIO))


def locate_stash_chest(ocr: OcrEngine) -> Point | None:
    """截屏 + OCR 定位仓库箱子点击点（客户区坐标）；找不到返回 None。"""
    image = screenshot_client()
    if image is None:
        return None
    label = find_stash_label(ocr.recognize_blocks(image), image.width, image.height)
    return None if label is None else chest_click_point(label)
