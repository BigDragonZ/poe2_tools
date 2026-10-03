#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""开发页测量单元测试：两点范围规范化（纯逻辑）与 ini [Measure] 读写回环。"""

from __future__ import annotations

from pathlib import Path

import pytest

from poe2_tools.config.settings import (
    MEASURE_POINT_COUNT,
    MEASURE_RANGE_COUNT,
    Point,
    Settings,
    load_settings,
    save_settings,
)
from poe2_tools.modules.measure import (
    MIN_RANGE_H,
    MIN_RANGE_W,
    MeasureError,
    normalize_range,
)


# ============================================================
# 两点 → 范围规范化
# ============================================================
def test_normalize_range_in_order() -> None:
    """左上拖到右下：原样返回。"""
    assert normalize_range(Point(100, 200), Point(160, 260)) == (100, 200, 160, 260)


def test_normalize_range_reversed() -> None:
    """反向拖拽（右下 → 左上）得到同一矩形。"""
    assert normalize_range(Point(160, 260), Point(100, 200)) == (100, 200, 160, 260)


def test_normalize_range_mixed_corners() -> None:
    """左下 → 右上：min/max 归一。"""
    assert normalize_range(Point(100, 260), Point(160, 200)) == (100, 200, 160, 260)


def test_normalize_range_clamped_to_client() -> None:
    """提供客户区尺寸时钳位到区内（负坐标/越界截断）。"""
    size = Point(200, 150)
    assert normalize_range(Point(-10, -20), Point(250, 180), size) == (0, 0, 200, 150)


def test_normalize_range_too_small_rejected() -> None:
    """范围小于最小尺寸（宽或高不足，如单击）视为误触，抛 MeasureError。"""
    with pytest.raises(MeasureError):
        normalize_range(Point(100, 100), Point(100 + MIN_RANGE_W - 1, 100 + 20))
    with pytest.raises(MeasureError):
        normalize_range(Point(100, 100), Point(100 + 20, 100 + MIN_RANGE_H - 1))


def test_normalize_range_min_size_accepted() -> None:
    """恰好等于最小尺寸时通过。"""
    rect = normalize_range(Point(100, 100), Point(100 + MIN_RANGE_W, 100 + MIN_RANGE_H))
    assert rect == (100, 100, 100 + MIN_RANGE_W, 100 + MIN_RANGE_H)


# ============================================================
# ini [Measure] 读写回环
# ============================================================
def test_measure_defaults_empty(tmp_path: Path) -> None:
    loaded = load_settings(tmp_path / "不存在.ini")
    assert loaded.dev.measure_points == {}
    assert loaded.dev.measure_ranges == {}


def test_measure_roundtrip(tmp_path: Path) -> None:
    ini = tmp_path / "test.ini"
    s = Settings()
    s.dev.measure_points[1] = Point(352, 238)
    s.dev.measure_points[MEASURE_POINT_COUNT] = Point(10, 20)
    s.dev.measure_ranges[2] = (100, 200, 300, 400)
    s.dev.measure_ranges[MEASURE_RANGE_COUNT] = (0, 0, 50, 60)
    save_settings(s, ini)

    loaded = load_settings(ini)
    assert loaded.dev.measure_points[1] == Point(352, 238)
    assert loaded.dev.measure_points[MEASURE_POINT_COUNT] == Point(10, 20)
    assert loaded.dev.measure_ranges[2] == (100, 200, 300, 400)
    assert loaded.dev.measure_ranges[MEASURE_RANGE_COUNT] == (0, 0, 50, 60)


def test_measure_invalid_ignored(tmp_path: Path) -> None:
    ini = tmp_path / "bad.ini"
    ini.write_text(
        "[Measure]\npoint1_x = 10\nrange1 = 1,2,3\nrange2 = 100,100,50,200\n",
        encoding="utf-8",
    )
    loaded = load_settings(ini)
    assert loaded.dev.measure_points == {}  # point1 缺 y
    assert loaded.dev.measure_ranges == {}  # range1 非四点，range2 x2 < x1
