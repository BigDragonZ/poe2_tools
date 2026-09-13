#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""背包整理模块单元测试：网格坐标计算与配置读写。"""

from __future__ import annotations

from pathlib import Path

import pytest

from poe2_tools import bag

from conftest import write_ini


# ============================================================
# 网格坐标计算
# ============================================================
def test_grid_points_row_major() -> None:
    points = list(bag.grid_points(100, 200, 50, 2, 3))
    assert points == [
        (100, 200), (150, 200), (200, 200),
        (100, 250), (150, 250), (200, 250),
    ]


def test_grid_points_fractional_cell_rounds() -> None:
    points = list(bag.grid_points(0, 0, 52.6, 1, 3))
    assert points == [(0, 0), (53, 0), (105, 0)]


def test_grid_points_single_cell() -> None:
    assert list(bag.grid_points(7, 9, 50, 1, 1)) == [(7, 9)]


# ============================================================
# 热键配置
# ============================================================
def test_dump_hotkey_default() -> None:
    assert bag.get_dump_hotkey() == bag.DEFAULT_DUMP_HOTKEY


def test_dump_hotkey_roundtrip() -> None:
    bag.set_dump_hotkey("f9")
    assert bag.get_dump_hotkey() == "f9"


def test_dump_hotkey_blank_falls_back(temp_ini: Path) -> None:
    write_ini(temp_ini, "Bag", {"DumpHotkey": "   "})
    assert bag.get_dump_hotkey() == bag.DEFAULT_DUMP_HOTKEY


# ============================================================
# 行列数配置
# ============================================================
def test_grid_size_default() -> None:
    assert bag.get_grid_size() == (bag.DEFAULT_ROWS, bag.DEFAULT_COLS)


def test_grid_size_roundtrip() -> None:
    bag.set_grid_size(6, 12)
    assert bag.get_grid_size() == (6, 12)


def test_grid_size_clamps_to_at_least_one() -> None:
    bag.set_grid_size(0, -3)
    assert bag.get_grid_size() == (1, 1)


def test_grid_size_invalid_falls_back(temp_ini: Path) -> None:
    write_ini(temp_ini, "Bag", {"Rows": "abc", "Cols": ""})
    assert bag.get_grid_size() == (bag.DEFAULT_ROWS, bag.DEFAULT_COLS)


# ============================================================
# 格子配置（标定结果）
# ============================================================
def test_grid_config_none_without_calibration() -> None:
    assert bag.get_grid_config() is None


@pytest.mark.parametrize("cell", ["0", "-5", "abc", ""])
def test_grid_config_none_with_invalid_cell(temp_ini: Path, cell: str) -> None:
    write_ini(temp_ini, "Bag", {"CellSize": cell})
    assert bag.get_grid_config() is None


def test_grid_config_ok(temp_ini: Path) -> None:
    write_ini(temp_ini, "Bag", {"CellSize": "52", "Rows": "5", "Cols": "11"})
    assert bag.get_grid_config() == (52.0, 5, 11)


def test_grid_config_uses_default_size(temp_ini: Path) -> None:
    write_ini(temp_ini, "Bag", {"CellSize": "52"})
    assert bag.get_grid_config() == (52.0, bag.DEFAULT_ROWS, bag.DEFAULT_COLS)


# ============================================================
# 配置文件编码
# ============================================================
def test_config_saved_as_utf8(temp_ini: Path) -> None:
    bag.set_dump_hotkey("f1")
    raw = temp_ini.read_bytes()
    raw.decode("utf-8")  # 不应抛出异常
    assert not raw.startswith(b"\xff\xfe") and not raw.startswith(b"\xfe\xff")
