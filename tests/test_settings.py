#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置模型单元测试：默认值、读写回环、非法值回退、货币坐标推导。"""

from __future__ import annotations

from pathlib import Path

import pytest

from poe2_tools.config import settings as sm
from poe2_tools.config.settings import (
    Point,
    Settings,
    currency_coord,
    load_settings,
    save_settings,
)

from conftest import write_ini


# ============================================================
# 默认值
# ============================================================
def test_defaults() -> None:
    s = load_settings()
    assert s.combat_hotkey == "f2"
    assert s.dump_hotkey == "f1"
    assert s.way_hotkey == "f6"
    assert s.map_hotkey == "f7"
    assert s.cell_size == 0
    assert (s.rows, s.cols) == (sm.DEFAULT_ROWS, sm.DEFAULT_COLS)
    assert s.active_profile == 1
    assert len(s.profiles) == sm.PROFILE_COUNT
    assert s.profiles[0]["LButton"].mode == sm.MODE_SPAM
    assert s.profiles[0]["q"].mode == sm.MODE_DISABLED
    assert set(s.cyclone.keys()) == set(sm.CYC_KEYS)


# ============================================================
# 读写回环
# ============================================================
def test_roundtrip(temp_ini: Path) -> None:
    s = Settings()
    s.cell_size = 70
    s.rows, s.cols = 6, 12
    s.way_currency = "ex"
    s.way_tier = 2
    s.currency["alch"] = Point(352, 238)
    s.cyclone_coords["q"] = Point(1918, 1375)
    s.profiles[1]["q"] = sm.KeyConfig(sm.MODE_SPAM, 4600, False)
    save_settings(s)

    loaded = load_settings()
    assert loaded.cell_size == 70
    assert (loaded.rows, loaded.cols) == (6, 12)
    assert loaded.way_currency == "ex" and loaded.way_tier == 2
    assert loaded.currency["alch"] == Point(352, 238)
    assert loaded.cyclone_coords["q"] == Point(1918, 1375)
    q = loaded.profiles[1]["q"]
    assert q.mode == sm.MODE_SPAM and q.interval_ms == 4600 and q.random_jitter is False


def test_saved_as_utf8(temp_ini: Path) -> None:
    save_settings(Settings())
    raw = temp_ini.read_bytes()
    raw.decode("utf-8")


# ============================================================
# 非法值回退与夹取
# ============================================================
def test_invalid_mode_falls_back(temp_ini: Path) -> None:
    write_ini(temp_ini, "Profile1", {"q_mode": "fly"})
    assert load_settings().profiles[0]["q"].mode == sm.MODE_DISABLED


def test_interval_clamped_to_minimum(temp_ini: Path) -> None:
    write_ini(temp_ini, "Profile1", {"q_mode": "spam", "q_interval": "10"})
    assert load_settings().profiles[0]["q"].interval_ms == sm.MIN_INTERVAL_MS


def test_batch_interval_clamped(temp_ini: Path) -> None:
    write_ini(temp_ini, "Waystone", {"Interval": "99999"})
    write_ini(temp_ini, "Map", {"Interval": "1"})
    s = load_settings()
    assert s.way_interval_ms == sm.MAX_BATCH_INTERVAL_MS
    assert s.map_interval_ms == sm.MIN_BATCH_INTERVAL_MS


def test_unknown_currency_falls_back(temp_ini: Path) -> None:
    write_ini(temp_ini, "Waystone", {"Currency": "mirror"})
    assert load_settings().way_currency == "alch"


def test_tier_clamped(temp_ini: Path) -> None:
    write_ini(temp_ini, "Waystone", {"Tier": "9"})
    assert load_settings().way_tier == 3


# ============================================================
# 货币坐标推导
# ============================================================
def test_currency_coord_unset_returns_none() -> None:
    assert currency_coord(Settings(), "alch") is None


def test_currency_coord_plain_ignores_tier() -> None:
    s = Settings()
    s.currency["alch"] = Point(100, 200)
    assert currency_coord(s, "alch", 3) == Point(100, 200)


@pytest.mark.parametrize(
    ("tier", "expected_x"),
    [(1, 100), (2, 100 + sm.TIER_SPACING), (3, 100 + 2 * sm.TIER_SPACING)],
)
def test_currency_coord_tiered_offsets(tier: int, expected_x: int) -> None:
    s = Settings()
    s.currency["ex"] = Point(100, 200)
    assert currency_coord(s, "ex", tier) == Point(expected_x, 200)
