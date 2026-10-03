#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷图 Q6 标定单元测试：两点 ROI 规范化（纯逻辑）与 ini 读写回环。"""

from __future__ import annotations

from pathlib import Path

import pytest

from poe2_tools.config.settings import Point, Settings, load_settings, save_settings
from poe2_tools.modules.mapping.calibrate import (
    MIN_ROI_H,
    MIN_ROI_W,
    CalibrateError,
    normalize_roi,
)


# ============================================================
# 两点 → ROI 规范化
# ============================================================
def test_normalize_roi_in_order() -> None:
    """先点左上角再点右下角：原样返回。"""
    assert normalize_roi(Point(100, 200), Point(130, 230)) == (100, 200, 130, 230)


def test_normalize_roi_reversed_order() -> None:
    """点击顺序任意：先右下后左上也能得到同一矩形。"""
    assert normalize_roi(Point(130, 230), Point(100, 200)) == (100, 200, 130, 230)


def test_normalize_roi_mixed_corners() -> None:
    """点的是左下 + 右上：min/max 归一。"""
    assert normalize_roi(Point(100, 230), Point(130, 200)) == (100, 200, 130, 230)


def test_normalize_roi_clamped_to_client() -> None:
    """提供客户区尺寸时钳位到区内（负坐标/越界截断）。"""
    size = Point(200, 150)
    assert normalize_roi(Point(-10, -20), Point(250, 180), size) == (0, 0, 200, 150)


def test_normalize_roi_too_small_rejected() -> None:
    """区域小于最小尺寸（宽或高不足）视为误触，抛 CalibrateError。"""
    with pytest.raises(CalibrateError):
        normalize_roi(Point(100, 100), Point(100 + MIN_ROI_W - 1, 100 + 20))
    with pytest.raises(CalibrateError):
        normalize_roi(Point(100, 100), Point(100 + 20, 100 + MIN_ROI_H - 1))


def test_normalize_roi_min_size_accepted() -> None:
    """恰好等于最小尺寸时通过。"""
    roi = normalize_roi(Point(100, 100), Point(100 + MIN_ROI_W, 100 + MIN_ROI_H))
    assert roi == (100, 100, 100 + MIN_ROI_W, 100 + MIN_ROI_H)


# ============================================================
# ini [Mapping] q6_roi 读写回环
# ============================================================
def test_settings_q6_roi_roundtrip(tmp_path: Path) -> None:
    ini = tmp_path / "test.ini"
    s = Settings()
    s.combat.q6_roi = (2100, 1350, 2124, 1370)
    save_settings(s, ini)
    loaded = load_settings(ini)
    assert loaded.combat.q6_roi == (2100, 1350, 2124, 1370)


def test_settings_q6_roi_default_none(tmp_path: Path) -> None:
    loaded = load_settings(tmp_path / "不存在.ini")
    assert loaded.combat.q6_roi is None


def test_settings_q6_roi_invalid_ignored(tmp_path: Path) -> None:
    ini = tmp_path / "bad.ini"
    ini.write_text("[Mapping]\nq6_roi = 1,2,3\n", encoding="utf-8")
    assert load_settings(ini).combat.q6_roi is None
    ini.write_text("[Mapping]\nq6_roi = 100,100,50,200\n", encoding="utf-8")  # x2 < x1
    assert load_settings(ini).combat.q6_roi is None
