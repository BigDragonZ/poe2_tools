#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷图自动化视觉纯函数单元测试：拾取黑框过滤管道、Q=6 点阵比对。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from poe2_tools.modules.mapping.loot import black_mask, clamp_roi, find_loot_box
from poe2_tools.modules.mapping.qstack import (
    binarize_roi,
    is_q_full,
    load_mask,
    mask_confidence,
    q6_roi_screen,
)

RESOLUTION = (400, 300)
LOOT_CFG = {
    "roi_size": 150,
    "black_v_max": 40,
    "aspect_ratio_min": 2.5,
    "aspect_ratio_max": 8.0,
    "area_min": 150,
    "area_max": 6000,
    "canny_threshold": [50, 150],
    "text_density_min": 0.08,
}


def _bright_frame() -> np.ndarray:
    """亮灰背景帧（BGR）。"""
    return np.full((RESOLUTION[1], RESOLUTION[0], 3), 200, dtype=np.uint8)


def _draw_bar_with_text(img: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> None:
    """画一条内部带白色「文字」笔触的黑色横条（模拟物品黑框）。"""
    cv2.rectangle(img, (x1, y1), (x2, y2), (0, 0, 0), -1)
    for x in range(x1 + 4, x2 - 4, 8):
        cv2.line(img, (x, y1 + 3), (x + 3, y2 - 3), (255, 255, 255), 1)


# ============================================================
# ROI 钳位
# ============================================================
def test_clamp_roi_center() -> None:
    assert clamp_roi(1280, 720, 150, (2560, 1440)) == (1205, 645, 1355, 795)


def test_clamp_roi_top_left_corner() -> None:
    assert clamp_roi(0, 0, 150, (2560, 1440)) == (0, 0, 75, 75)


def test_clamp_roi_bottom_right_corner() -> None:
    assert clamp_roi(2560, 1440, 150, (2560, 1440)) == (2485, 1365, 2560, 1440)


def test_clamp_roi_negative_cursor() -> None:
    assert clamp_roi(-10, -10, 150, (2560, 1440)) == (0, 0, 65, 65)


# ============================================================
# 黑框过滤管道
# ============================================================
def test_black_mask_v_threshold() -> None:
    img = np.zeros((4, 4, 3), dtype=np.uint8)
    img[0, 0] = (40, 40, 40)   # V=40 恰好通过
    img[0, 1] = (41, 41, 41)   # V=41 不通过
    mask = black_mask(img, 40)
    assert mask[0, 0] == 255
    assert mask[0, 1] == 0
    assert mask[3, 3] == 255


def test_find_loot_box_accepts_text_bar() -> None:
    img = _bright_frame()
    _draw_bar_with_text(img, 150, 130, 250, 146)  # 100x16，长宽比 6.25
    center = find_loot_box(img, 200, 138, LOOT_CFG, RESOLUTION)
    assert center is not None
    assert abs(center[0] - 200) <= 2
    assert abs(center[1] - 138) <= 2


def test_find_loot_box_rejects_plain_shadow() -> None:
    """纯黑横条（无文字）文本密度不足，拒绝。"""
    img = _bright_frame()
    cv2.rectangle(img, (150, 130), (250, 146), (0, 0, 0), -1)
    assert find_loot_box(img, 200, 138, LOOT_CFG, RESOLUTION) is None


def test_find_loot_box_rejects_square() -> None:
    """正方形轮廓长宽比不符，拒绝。"""
    img = _bright_frame()
    cv2.rectangle(img, (170, 118), (230, 178), (0, 0, 0), -1)
    _draw_noise_inside(img, 170, 118, 230, 178)
    assert find_loot_box(img, 200, 148, LOOT_CFG, RESOLUTION) is None


def _draw_noise_inside(img: np.ndarray, x1: int, y1: int, x2: int, y2: int) -> None:
    for x in range(x1 + 2, x2 - 2, 6):
        for y in range(y1 + 2, y2 - 2, 6):
            cv2.circle(img, (x, y), 1, (255, 255, 255), -1)


def test_find_loot_box_rejects_oversize() -> None:
    """面积超上限的大黑块，拒绝。"""
    img = _bright_frame()
    cv2.rectangle(img, (130, 126), (270, 174), (0, 0, 0), -1)  # 140x48，面积超 6000
    _draw_noise_inside(img, 130, 126, 270, 174)
    assert find_loot_box(img, 200, 150, LOOT_CFG, RESOLUTION) is None


def test_find_loot_box_none_when_bright() -> None:
    assert find_loot_box(_bright_frame(), 200, 150, LOOT_CFG, RESOLUTION) is None


def test_find_loot_box_cursor_at_frame_corner() -> None:
    """光标贴角落：ROI 钳位不越界，框在角落也能检出。"""
    img = _bright_frame()
    _draw_bar_with_text(img, 10, 10, 110, 26)
    center = find_loot_box(img, 5, 5, LOOT_CFG, RESOLUTION)
    assert center is not None


def test_find_loot_box_empty_frame() -> None:
    assert find_loot_box(np.zeros((0, 0, 3), dtype=np.uint8), 0, 0, LOOT_CFG, RESOLUTION) is None


# ============================================================
# Q=6 点阵比对（F5 标定紧框 + templates/q6.png）
# ============================================================
def _make_six_image(width: int = 60, height: int = 60) -> np.ndarray:
    """合成暗底白字「6」的 BGR 图。"""
    img = np.full((height, width, 3), 30, dtype=np.uint8)
    cv2.putText(
        img, "6", (width // 5, height * 4 // 5),
        cv2.FONT_HERSHEY_SIMPLEX, height / 40.0, (255, 255, 255), max(1, height // 30),
    )
    return img


def test_mask_confidence_exact_and_partial() -> None:
    # 像素点间隔 >2px，避免容差膨胀桥接相邻点
    mask = np.zeros((20, 20), dtype=np.uint8)
    for y, x in [(2, 2), (2, 18), (18, 2), (18, 18)]:
        mask[y, x] = 1
    assert mask_confidence(mask, mask) == 1.0
    partial = mask.copy()
    partial[2, 2] = 0  # 命中 3/4
    assert mask_confidence(partial, mask) == 0.75


def test_mask_confidence_tolerates_1px_shift() -> None:
    """容差语义：1px 偏移仍全命中，3px 偏移显著失配。"""
    mask = np.zeros((20, 20), dtype=np.uint8)
    cv2.circle(mask, (10, 10), 4, 1, -1)
    shift1 = cv2.warpAffine(
        mask.astype(np.float32), np.float32([[1, 0, 1], [0, 1, 0]]), (20, 20)
    )
    assert mask_confidence((shift1 > 0).astype(np.uint8), mask) == 1.0
    shift3 = cv2.warpAffine(
        mask.astype(np.float32), np.float32([[1, 0, 3], [0, 1, 0]]), (20, 20)
    )
    assert mask_confidence((shift3 > 0).astype(np.uint8), mask) < 0.92


def test_mask_confidence_shape_mismatch_and_empty() -> None:
    a = np.zeros((20, 20), dtype=np.uint8)
    b = np.zeros((10, 10), dtype=np.uint8)
    assert mask_confidence(a, b) == 0.0
    assert mask_confidence(a, a) == 0.0  # 空掩模


def test_is_q_full_pipeline() -> None:
    """自适应二值化 + 掩模比对：原图命中，纯黑图不命中。"""
    img = _make_six_image()
    mask = binarize_roi(img)
    assert mask.sum() > 0
    assert is_q_full(img, mask, 0.92)
    dark = np.full((60, 60, 3), 30, dtype=np.uint8)
    assert not is_q_full(dark, mask, 0.92)


def test_is_q_full_with_cd_shadow_and_noise() -> None:
    """CD 扇形阴影（局部变暗）+ 少量噪点变体仍应满足 0.92 阈值。"""
    img = _make_six_image()
    mask = binarize_roi(img)
    variant = img.copy()
    variant[:, :30] = (variant[:, :30] // 3).astype(np.uint8)  # 左侧扇形阴影
    rng = np.random.default_rng(7)
    # 随机熄灭 2% 的亮像素（噪点）
    binary = binarize_roi(variant)
    lit = np.argwhere(binary == 1)
    drop = rng.choice(len(lit), size=max(1, len(lit) // 50), replace=False)
    for y, x in lit[drop]:
        variant[y, x] = 30
    assert is_q_full(variant, mask, 0.92)


def test_is_q_full_no_mask_disabled() -> None:
    """无掩模（未标定/未截图）时判定为不满足，不崩溃。"""
    assert not is_q_full(_make_six_image(), None, 0.92)


def test_q6_roi_screen() -> None:
    """ini q6_roi（客户区坐标）→ 屏幕坐标。"""
    assert q6_roi_screen(100, 200, (2100, 1350, 2120, 1370)) == (2200, 1550, 2220, 1570)


def test_q6_tight_box_detect_match_and_miss(tmp_path: Path) -> None:
    """紧框模板：相同内容命中，换成其他数字不命中。"""
    img = _make_six_image(24, 20)
    path = tmp_path / "q6.png"
    cv2.imwrite(str(path), img)
    mask = load_mask(path)
    assert mask is not None
    assert mask.shape == (20, 24)
    # 模拟整帧：客户区原点 (100,200) + q6_roi(2100,1350,2124,1370)
    frame = np.full((1600, 2600, 3), 30, dtype=np.uint8)
    x1, y1, x2, y2 = q6_roi_screen(100, 200, (2100, 1350, 2124, 1370))
    frame[y1:y2, x1:x2] = img
    assert is_q_full(frame[y1:y2, x1:x2], mask, 0.92)
    # 换成「3」：同区域内容不同 → 不命中
    other = np.full((20, 24, 3), 30, dtype=np.uint8)
    cv2.putText(other, "3", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    assert not is_q_full(other, mask, 0.92)


def test_load_mask_missing_or_blank(tmp_path: Path) -> None:
    """无文件 → None；纯黑截图（无数值）→ None（禁用 COMBOS 不崩溃）。"""
    assert load_mask(tmp_path / "不存在.png") is None
    blank = tmp_path / "q6.png"
    cv2.imwrite(str(blank), np.full((20, 24, 3), 30, dtype=np.uint8))
    assert load_mask(blank) is None
