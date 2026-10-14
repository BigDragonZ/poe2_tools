#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""配置模型单元测试：默认值、新段读写回环、旧段回退兼容、非法值回退、货币坐标推导。"""

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
    assert s.combat.hotkey == "f2"
    assert s.general.sort.hotkey == "f1"
    assert s.general.tablet.hotkey == "f6"
    assert s.general.map_click.hotkey == "f7"
    assert s.general.sort.cell_size == 0
    assert (s.general.sort.rows, s.general.sort.cols) == (sm.DEFAULT_ROWS, sm.DEFAULT_COLS)
    assert s.combat.active_profile == 1
    assert len(s.combat.profiles) == sm.PROFILE_COUNT
    assert s.combat.profiles[0]["LButton"].mode == sm.MODE_SPAM
    assert s.combat.profiles[0]["q"].mode == sm.MODE_DISABLED
    assert s.dev.debug is False
    assert s.dev.log_level == "INFO"


# ============================================================
# 读写回环（新段名）
# ============================================================
def test_roundtrip(temp_ini: Path) -> None:
    s = Settings()
    s.general.sort.cell_size = 70
    s.general.sort.rows, s.general.sort.cols = 6, 12
    s.general.tablet.currency = "ex"
    s.general.tablet.tier = 2
    s.currency["alch"] = Point(352, 238)
    s.combat.profiles[0]["q"] = sm.KeyConfig(sm.MODE_SPAM, 4600, 690)
    s.dev.debug = True
    s.dev.log_level = "DEBUG"
    save_settings(s)

    loaded = load_settings()
    assert loaded.general.sort.cell_size == 70
    assert (loaded.general.sort.rows, loaded.general.sort.cols) == (6, 12)
    assert loaded.general.tablet.currency == "ex" and loaded.general.tablet.tier == 2
    assert loaded.currency["alch"] == Point(352, 238)
    q = loaded.combat.profiles[0]["q"]
    assert q.mode == sm.MODE_SPAM and q.interval_ms == 4600 and q.jitter_ms == 690
    assert loaded.dev.debug is True
    assert loaded.dev.log_level == "DEBUG"


def test_saved_uses_new_sections(temp_ini: Path) -> None:
    save_settings(Settings())
    text = temp_ini.read_text(encoding="utf-8")
    for section in ("[Combat]", "[Sort]", "[Tablet]", "[Map]",
                    "[Profile1]", "[Currency]", "[Measure]", "[Dev]"):
        assert section in text
    for legacy in ("[General]", "[Waystone]", "[Bag]", "[Cyclone]", "[Mapping]", "[Bridge]"):
        assert legacy not in text


def test_saved_as_utf8(temp_ini: Path) -> None:
    save_settings(Settings())
    raw = temp_ini.read_bytes()
    raw.decode("utf-8")


# ============================================================
# 旧段回退兼容
# ============================================================
def test_legacy_sections_fallback(temp_ini: Path) -> None:
    """只含旧段的 ini 能正确读入新模型。"""
    temp_ini.write_text(
        "[General]\nCombatHotkey = f9\nDumpHotkey = f3\nActiveProfile = 2\n"
        "[Waystone]\nHotkey = f10\nCurrency = ex\nTier = 2\nInterval = 250\n"
        "[Bag]\nRows = 6\nCols = 12\nDumpInterval = 45\nCellSize = 68\n",
        encoding="utf-8",
    )
    s = load_settings()
    assert s.combat.hotkey == "f9"
    # 旧值 2（旋风页序号）在旋风重构后不再是配置，夹取回普通配置页 1
    assert s.combat.active_profile == 1
    assert s.general.sort.hotkey == "f3"
    assert (s.general.sort.rows, s.general.sort.cols) == (6, 12)
    assert s.general.sort.interval_ms == 45
    assert s.general.sort.cell_size == 68
    assert s.general.tablet.hotkey == "f10"
    assert s.general.tablet.currency == "ex"
    assert s.general.tablet.tier == 2
    assert s.general.tablet.interval_ms == 250


def test_new_section_takes_precedence_over_legacy(temp_ini: Path) -> None:
    """新旧段并存时以新段为准。"""
    temp_ini.write_text(
        "[General]\nCombatHotkey = f9\n"
        "[Combat]\nHotkey = f2\n"
        "[Bag]\nCellSize = 70\n"
        "[Sort]\nCellSize = 52\n",
        encoding="utf-8",
    )
    s = load_settings()
    assert s.combat.hotkey == "f2"
    assert s.general.sort.cell_size == 52


# ============================================================
# 非法值回退与夹取
# ============================================================
def test_invalid_mode_falls_back(temp_ini: Path) -> None:
    write_ini(temp_ini, "Profile1", {"q_mode": "fly"})
    assert load_settings().combat.profiles[0]["q"].mode == sm.MODE_DISABLED


def test_interval_clamped_to_minimum(temp_ini: Path) -> None:
    write_ini(temp_ini, "Profile1", {"q_mode": "spam", "q_interval": "10"})
    assert load_settings().combat.profiles[0]["q"].interval_ms == sm.MIN_INTERVAL_MS


def test_jitter_ms_read_directly(temp_ini: Path) -> None:
    write_ini(temp_ini, "Profile1", {"q_jitter": "120"})
    assert load_settings().combat.profiles[0]["q"].jitter_ms == 120


def test_jitter_ms_clamped_to_range(temp_ini: Path) -> None:
    write_ini(temp_ini, "Profile1", {"q_jitter": "-5", "w_jitter": "99999"})
    s = load_settings()
    assert s.combat.profiles[0]["q"].jitter_ms == 0
    assert s.combat.profiles[0]["w"].jitter_ms == sm.MAX_BATCH_INTERVAL_MS


def test_legacy_random_switch_converts(temp_ini: Path) -> None:
    # 旧版布尔键 _random：1 → 间隔的 15%，0 → 0
    write_ini(temp_ini, "Profile1", {"q_interval": "1000", "q_random": "1", "w_random": "0"})
    s = load_settings()
    assert s.combat.profiles[0]["q"].jitter_ms == 150
    assert s.combat.profiles[0]["w"].jitter_ms == 0


def test_batch_interval_clamped(temp_ini: Path) -> None:
    write_ini(temp_ini, "Tablet", {"Interval": "99999"})
    write_ini(temp_ini, "Map", {"Interval": "1"})
    s = load_settings()
    assert s.general.tablet.interval_ms == sm.MAX_BATCH_INTERVAL_MS
    assert s.general.map_click.interval_ms == sm.MIN_BATCH_INTERVAL_MS


def test_batch_interval_clamped_legacy(temp_ini: Path) -> None:
    """旧段名写入同样触发批量间隔夹取。"""
    write_ini(temp_ini, "Waystone", {"Interval": "99999"})
    s = load_settings()
    assert s.general.tablet.interval_ms == sm.MAX_BATCH_INTERVAL_MS


def test_unknown_currency_falls_back(temp_ini: Path) -> None:
    write_ini(temp_ini, "Tablet", {"Currency": "mirror"})
    assert load_settings().general.tablet.currency == "alch"


def test_tier_clamped(temp_ini: Path) -> None:
    write_ini(temp_ini, "Tablet", {"Tier": "9"})
    assert load_settings().general.tablet.tier == 3


def test_active_profile_clamped(temp_ini: Path) -> None:
    """旋风页不再是配置：ActiveProfile 夹取到普通配置页范围。"""
    write_ini(temp_ini, "Combat", {"ActiveProfile": "99"})
    assert load_settings().combat.active_profile == sm.PROFILE_COUNT


def test_legacy_cyclone_section_ignored(temp_ini: Path) -> None:
    """旧 [Cyclone] 段（鼠标三键策略）读取时忽略，保存后自然消失。"""
    write_ini(temp_ini, "Cyclone", {"LButton_mode": "spam", "LButton_interval": "100"})
    s = load_settings()
    save_settings(s)
    assert "[Cyclone]" not in temp_ini.read_text(encoding="utf-8")


def test_dev_log_level_invalid_falls_back(temp_ini: Path) -> None:
    write_ini(temp_ini, "Dev", {"LogLevel": "verbose", "Debug": "1"})
    s = load_settings()
    assert s.dev.log_level == "INFO"
    assert s.dev.debug is True


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


# ============================================================
# 分辨率坐标档（@宽x高 分档段）
# ============================================================
RES = Point(1600, 1024)
RES_OTHER = Point(2560, 1440)


def test_profile_section_naming() -> None:
    assert sm._profile_section("StashUI", RES) == "StashUI@1600x1024"
    assert sm._profile_section("StashUI", None) == "StashUI"
    s = Settings()
    assert s.coords_profile == ""
    s.resolution = RES
    assert s.coords_profile == "1600x1024"


def test_resolve_section_prefers_profile(temp_ini: Path) -> None:
    """基础段与档段并存时读到档段值。"""
    write_ini(temp_ini, "Currency", {"alch_x": "100", "alch_y": "200"})
    write_ini(temp_ini, "Currency@1600x1024", {"alch_x": "300", "alch_y": "400"})
    write_ini(temp_ini, "Sort", {"CellSize": "50"})
    write_ini(temp_ini, "Sort@1600x1024", {"CellSize": "66"})
    s = load_settings(resolution=RES)
    assert s.currency["alch"] == Point(300, 400)
    assert s.general.sort.cell_size == 66
    assert s.coords_profile_exists is True


def test_resolve_section_legacy_fallback(temp_ini: Path) -> None:
    """无任何 @ 变体的老配置：任一分辨率回退基础段，但档标记为不存在。"""
    write_ini(temp_ini, "Currency", {"alch_x": "100", "alch_y": "200"})
    write_ini(temp_ini, "Sort", {"CellSize": "50"})
    s = load_settings(resolution=RES)
    assert s.currency["alch"] == Point(100, 200)
    assert s.general.sort.cell_size == 50
    assert s.coords_profile_exists is False


def test_resolve_section_no_cross_resolution_fallback(temp_ini: Path) -> None:
    """已有其他分辨率档时绝不回退基础段（杜绝跨分辨率坐标污染）。"""
    write_ini(temp_ini, "Currency", {"alch_x": "100", "alch_y": "200"})
    write_ini(temp_ini, "Currency@2560x1440", {"alch_x": "300", "alch_y": "400"})
    write_ini(temp_ini, "Sort", {"CellSize": "50"})
    write_ini(temp_ini, "Sort@2560x1440", {"CellSize": "80"})
    s = load_settings(resolution=RES)
    assert s.currency == {}
    assert s.general.sort.cell_size == 0
    assert s.coords_profile_exists is False


def test_save_writes_profile_and_base(temp_ini: Path) -> None:
    """带分辨率保存：基础段与档段双写；Sort 档段仅含 CellSize。"""
    s = Settings(resolution=RES)
    s.general.sort.cell_size = 70
    s.currency["alch"] = Point(352, 238)
    save_settings(s)
    text = temp_ini.read_text(encoding="utf-8")
    assert "[StashUI]" in text and "[StashUI@1600x1024]" in text
    assert "[Currency@1600x1024]" in text and "[Measure@1600x1024]" in text
    assert "[Sort@1600x1024]" in text
    # 档优先读取回来
    loaded = load_settings(resolution=RES)
    assert loaded.general.sort.cell_size == 70
    assert loaded.currency["alch"] == Point(352, 238)
    assert loaded.coords_profile_exists is True
    # Sort 档段只有 CellSize 一键
    import configparser
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read(temp_ini, encoding="utf-8")
    assert list(config["Sort@1600x1024"].keys()) == ["CellSize"]


def test_save_preserves_other_profiles(temp_ini: Path) -> None:
    """读改写：以一个分辨率保存不抹掉其他分辨率档段。"""
    s1 = Settings(resolution=RES)
    s1.currency["alch"] = Point(100, 200)
    s1.general.sort.cell_size = 66
    save_settings(s1)
    s2 = Settings(resolution=RES_OTHER)
    s2.currency["alch"] = Point(300, 400)
    s2.general.sort.cell_size = 80
    save_settings(s2)
    text = temp_ini.read_text(encoding="utf-8")
    assert "[Currency@1600x1024]" in text and "[Currency@2560x1440]" in text
    assert "[Sort@1600x1024]" in text and "[Sort@2560x1440]" in text
    assert load_settings(resolution=RES).currency["alch"] == Point(100, 200)
    assert load_settings(resolution=RES_OTHER).currency["alch"] == Point(300, 400)
    assert load_settings(resolution=RES).general.sort.cell_size == 66
    assert load_settings(resolution=RES_OTHER).general.sort.cell_size == 80


def test_profile_roundtrip_isolated(temp_ini: Path) -> None:
    """档回环：写 R 档后以 R 读取一致，以其他分辨率读取为未标定。"""
    s = Settings(resolution=RES)
    s.currency["ex"] = Point(500, 600)
    s.dev.measure_points[1] = Point(10, 20)
    s.dev.measure_ranges[1] = (1, 2, 30, 40)
    save_settings(s)
    loaded = load_settings(resolution=RES)
    assert loaded.currency["ex"] == Point(500, 600)
    assert loaded.dev.measure_points[1] == Point(10, 20)
    assert loaded.dev.measure_ranges[1] == (1, 2, 30, 40)
    other = load_settings(resolution=RES_OTHER)
    assert other.currency == {}
    assert other.dev.measure_points == {}
    assert other.coords_profile_exists is False


def test_no_resolution_legacy_behavior(temp_ini: Path) -> None:
    """resolution=None 时读写与分档前完全一致（不产生档段）。"""
    s = Settings()
    s.currency["alch"] = Point(352, 238)
    s.general.sort.cell_size = 70
    save_settings(s)
    text = temp_ini.read_text(encoding="utf-8")
    assert "@" not in text
    loaded = load_settings()
    assert loaded.currency["alch"] == Point(352, 238)
    assert loaded.general.sort.cell_size == 70
    assert loaded.resolution is None
    assert loaded.coords_profile_exists is True


def test_migration_materialize(temp_ini: Path) -> None:
    """老配置（仅基础段）经 load(R) → save 物化为当前分辨率档。"""
    write_ini(temp_ini, "Currency", {"alch_x": "100", "alch_y": "200"})
    write_ini(temp_ini, "Sort", {"CellSize": "50"})
    write_ini(temp_ini, "StashUI", {"GridCell": "52"})
    s = load_settings(resolution=RES)
    assert s.coords_profile_exists is False  # 尚未物化
    save_settings(s)
    reloaded = load_settings(resolution=RES)
    assert reloaded.coords_profile_exists is True
    assert reloaded.currency["alch"] == Point(100, 200)
    assert reloaded.general.sort.cell_size == 50
    assert reloaded.stash_ui.stash_grid_cell == 52
