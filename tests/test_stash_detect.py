#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""仓库箱子标签定位单元测试（纯逻辑：OCR 文本块 → 点击点）。"""

from __future__ import annotations

from poe2_tools.core.ocr import TextBlock
from poe2_tools.modules.stash.detect import chest_click_point, find_stash_label

W, H = 2560, 1440


def _block(text: str, cx: float, cy: float, h: float = 36.0) -> TextBlock:
    return TextBlock(text=text, cx=cx, cy=cy, h=h)


def test_find_world_label() -> None:
    """正常命中：世界中的「倉庫」牌匾标签。"""
    blocks = [_block("希爾妲", 770, 60), _block("倉庫", 851, 373)]
    label = find_stash_label(blocks, W, H)
    assert label is not None and label.cx == 851


def test_ocr_misread_variants() -> None:
    """OCR 误读变体（合库/食库）也能命中。"""
    for text in ("倉庫", "合库", "食库", "仓库"):
        blocks = [_block(text, 851, 373)]
        assert find_stash_label(blocks, W, H) is not None, text


def test_exclude_map_panel_region() -> None:
    """右上角地图面板里的「倉庫」字样必须排除。"""
    blocks = [_block("食库", 2252, 84)]  # 地图面板内
    assert find_stash_label(blocks, W, H) is None


def test_world_label_wins_over_map_panel() -> None:
    """两处都有时取世界标签（地图面板被排除）。"""
    blocks = [_block("食库", 2252, 84, h=51), _block("合库", 851, 373, h=36)]
    label = find_stash_label(blocks, W, H)
    assert label is not None and label.cx == 851


def test_unrelated_labels_ignored() -> None:
    """NPC 名与其他牌匾（聖域鎖櫃/地圖裝置）不匹配。"""
    blocks = [
        _block("希爾妲", 770, 60),
        _block("聖域鎖", 1095, 193),
        _block("聖域鎖櫃", 1095, 193),
        _block("地圖裝置", 1248, 823),
        _block("安潔", 2020, 483),
    ]
    assert find_stash_label(blocks, W, H) is None


def test_empty_blocks() -> None:
    assert find_stash_label([], W, H) is None


def test_chest_click_point_below_label() -> None:
    """点击点在标签中心下方（点箱子本体），横向不变。"""
    point = chest_click_point(_block("倉庫", 851, 373, h=36))
    assert point.x == 851
    assert point.y == round(373 + 36 * 1.2)
