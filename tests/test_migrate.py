#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""AHK 配置迁移单元测试：混合编码解码与字段映射。"""

from __future__ import annotations

from poe2_tools.config import settings as sm
from poe2_tools.config.migrate import decode_ahk_ini, merge_ahk_coords, migrate_ahk_config
from poe2_tools.config.settings import Point, Settings


def _build_ahk_ini() -> bytes:
    """构造混合编码 AHK ini：UTF-8 BOM + ASCII + GBK 节名「配置N」。"""
    text = (
        "[General]\r\nActiveProfile=5\r\nCombatHotkey=F2\r\nDumpHotkey=F1\r\n"
        "[Bag]\r\nCellSize=70\r\nRows=5\r\nCols=11\r\nDumpInterval=20\r\n"
        "[Currency]\r\nalch_x=352\r\nalch_y=238\r\nex_x=81\r\nex_y=505\r\n"
        "[Waystone]\r\nHotkey=F6\r\nCurrency=alch\r\nTier=1\r\nInterval=50\r\n"
        "[Map]\r\nHotkey=F7\r\nInterval=50\r\n"
        "[Cyclone]\r\nLButton_mode=2\r\nLButton_interval=100\r\nLButton_random=1\r\n"
        "MButton_mode=1\r\nMButton_interval=100\r\nMButton_random=1\r\n"
        "RButton_mode=1\r\nRButton_interval=100\r\nRButton_random=1\r\n"
        "q_x=1918\r\nq_y=1375\r\ne_x=1989\r\ne_y=1371\r\nq_text=\r\ne_text=\r\n"
    )
    # 配置1：GBK 编码节名 + q 连点 4600ms 无抖动
    profile = (
        "[配置1]\r\nLButton_mode=2\r\nLButton_interval=100\r\nLButton_random=1\r\n"
        "RButton_mode=1\r\nRButton_interval=300\r\nRButton_random=1\r\n"
        "Space_mode=1\r\nSpace_interval=300\r\nSpace_random=1\r\n"
        "q_mode=2\r\nq_interval=4600\r\nq_random=0\r\n"
        "w_mode=1\r\nw_interval=300\r\nw_random=1\r\n"
        "e_mode=2\r\ne_interval=3280\r\ne_random=0\r\n"
        "r_mode=1\r\nr_interval=300\r\nr_random=1\r\n"
        "t_mode=1\r\nt_interval=300\r\nt_random=1\r\n"
    )
    return b"\xef\xbb\xbf\r\n" + text.encode("ascii") + profile.encode("gbk")


def test_decode_mixed_encoding() -> None:
    text = decode_ahk_ini(_build_ahk_ini())
    assert "[配置1]" in text
    assert "CellSize=70" in text
    assert not text.startswith("\ufeff")


def test_decode_pure_utf8() -> None:
    raw = "[Bag]\r\nCellSize=52\r\n".encode("utf-8")
    assert decode_ahk_ini(raw).startswith("[Bag]")


def test_migrate_general_and_bag() -> None:
    s = migrate_ahk_config(_build_ahk_ini())
    assert s.combat_hotkey.lower() == "f2"
    assert s.active_profile == 5
    assert s.cell_size == 70
    assert s.dump_interval_ms == 20


def test_migrate_currency_and_cyclone_coords() -> None:
    s = migrate_ahk_config(_build_ahk_ini())
    assert s.currency["alch"] == Point(352, 238)
    assert s.currency["ex"] == Point(81, 505)
    assert s.cyclone_coords["q"] == Point(1918, 1375)
    assert s.cyclone_coords["e"] == Point(1989, 1371)


def test_migrate_mode_mapping() -> None:
    s = migrate_ahk_config(_build_ahk_ini())
    profile1 = s.profiles[0]
    assert profile1["LButton"].mode == sm.MODE_SPAM
    assert profile1["RButton"].mode == sm.MODE_DISABLED
    q = profile1["q"]
    assert q.mode == sm.MODE_SPAM and q.interval_ms == 4600 and q.random_jitter is False
    e = profile1["e"]
    assert e.mode == sm.MODE_SPAM and e.interval_ms == 3280


def test_migrate_cyclone_mouse_keys() -> None:
    s = migrate_ahk_config(_build_ahk_ini())
    assert s.cyclone["LButton"].mode == sm.MODE_SPAM
    assert s.cyclone["MButton"].mode == sm.MODE_DISABLED


def test_migrate_unconfigured_profiles_use_defaults() -> None:
    s = migrate_ahk_config(_build_ahk_ini())
    # 只有配置1 有数据，配置2-4 保持默认
    assert s.profiles[1]["LButton"].mode == sm.MODE_SPAM
    assert s.profiles[1]["q"].mode == sm.MODE_DISABLED


# ============================================================
# 增量坐标合并
# ============================================================
def test_merge_coords_fills_missing() -> None:
    s = Settings()
    synced = merge_ahk_coords(s, _build_ahk_ini())
    assert s.currency["alch"] == Point(352, 238)
    assert s.currency["ex"] == Point(81, 505)
    assert s.cyclone_coords["q"] == Point(1918, 1375)
    assert "currency:alch" in synced and "cyclone:q" in synced
    assert "cyclone:e" in synced


def test_merge_coords_keeps_existing() -> None:
    s = Settings()
    s.currency["alch"] = Point(999, 999)
    s.cyclone_coords["q"] = Point(1, 1)
    synced = merge_ahk_coords(s, _build_ahk_ini())
    assert s.currency["alch"] == Point(999, 999)  # 已标定的不覆盖
    assert s.cyclone_coords["q"] == Point(1, 1)
    assert "currency:alch" not in synced and "cyclone:q" not in synced
    assert s.currency["ex"] == Point(81, 505)  # 缺失的仍填充


def test_merge_coords_does_not_touch_other_settings() -> None:
    s = Settings()
    s.cell_size = 72
    merge_ahk_coords(s, _build_ahk_ini())
    assert s.cell_size == 72  # AHK 里 CellSize=70，合并不覆盖
