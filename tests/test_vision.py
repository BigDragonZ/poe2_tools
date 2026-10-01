#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视觉检测单元测试：模板匹配、白色像素兜底、边沿触发（合成图像）。"""

from __future__ import annotations

import numpy as np

from poe2_tools.core.vision import EdgeTrigger, has_bright_pixel, match_template


def _black(h: int = 40, w: int = 40) -> np.ndarray:
    return np.zeros((h, w, 3), dtype=np.uint8)


def _digit_template() -> np.ndarray:
    """模拟数字图案：白底黑竖条（非常量，归一化匹配有意义）。"""
    template = np.full((12, 8, 3), 255, dtype=np.uint8)
    template[:, 3:5] = 0
    return template


# ============================================================
# 模板匹配
# ============================================================
def test_match_template_hit() -> None:
    region = _black()
    region[10:22, 20:28] = _digit_template()
    assert match_template(region, _digit_template()) is True


def test_match_template_miss() -> None:
    assert match_template(_black(), _digit_template()) is False


def test_match_template_constant_template_rejected() -> None:
    template = np.full((8, 8, 3), 255, dtype=np.uint8)
    region = _black()
    region[10:18, 20:28] = template
    assert match_template(region, template) is False  # 常量模板无意义


def test_match_template_empty_inputs() -> None:
    assert match_template(np.array([]), np.array([])) is False
    assert match_template(_black(4, 4), _digit_template()) is False  # 模板大于区域


def test_match_template_threshold() -> None:
    template = _digit_template()
    noisy = template.copy()
    noisy[:6] = 0  # 上半块不同 → 相似度明显下降
    region = _black()
    region[10:22, 20:28] = noisy
    assert match_template(region, template, threshold=0.99) is False
    assert match_template(region, template, threshold=0.4) is True


# ============================================================
# 白色像素兜底
# ============================================================
def test_has_bright_pixel_hit() -> None:
    region = _black()
    region[5, 5] = (255, 255, 255)
    assert has_bright_pixel(region) is True


def test_has_bright_pixel_respects_tolerance() -> None:
    region = _black()
    region[5, 5] = (236, 236, 236)  # 容差 ±20 内
    assert has_bright_pixel(region, tolerance=20) is True
    region[5, 5] = (200, 200, 200)
    assert has_bright_pixel(region, tolerance=20) is False


def test_has_bright_pixel_empty() -> None:
    assert has_bright_pixel(np.array([])) is False


# ============================================================
# 边沿触发
# ============================================================
def test_edge_trigger_fires_once_on_rising_edge() -> None:
    edge = EdgeTrigger()
    assert edge.update(False) is False
    assert edge.update(True) is True   # 上升沿：触发一次
    assert edge.update(True) is False  # 持续存在：不再触发
    assert edge.update(False) is False
    assert edge.update(True) is True   # 再次出现：重新触发


def test_edge_trigger_reset() -> None:
    edge = EdgeTrigger()
    edge.update(True)
    edge.reset()
    assert edge.update(True) is True
