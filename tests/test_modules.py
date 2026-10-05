#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战斗宏与地图速点单元测试：启动前置检查与配置选择（不触发真实输入）。"""

from __future__ import annotations

import pytest

from poe2_tools.config import settings as sm
from poe2_tools.config.settings import KeyConfig, Point, Settings
from poe2_tools.modules import combat as combat_module
from poe2_tools.modules.combat import CombatMacro
from poe2_tools.modules.map_runner import MapRunner
from poe2_tools.modules.bag import BagOrganizer


# ============================================================
# 战斗宏
# ============================================================
def test_macro_refuses_when_poe_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(combat_module.window, "is_poe_active", lambda: False)
    macro = CombatMacro(Settings())
    macro.start()
    assert not macro.active


def test_macro_refuses_when_all_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(combat_module.window, "is_poe_active", lambda: True)
    s = Settings()
    for profile in s.combat.profiles:
        for key in profile:
            profile[key] = KeyConfig(sm.MODE_DISABLED)
    s.combat.active_profile = 1
    macro = CombatMacro(s)
    macro.start()
    assert not macro.active


def test_current_config_profile_selection() -> None:
    s = Settings()
    s.combat.active_profile = 1
    macro = CombatMacro(s)
    keys, cfg = macro._current_config()
    assert keys == sm.SKILL_KEYS
    assert cfg is s.combat.profiles[0]


# ============================================================
# 地图速点
# ============================================================
def test_map_missing_currencies_when_uncalibrated() -> None:
    runner = MapRunner(Settings(), BagOrganizer(Settings()))
    assert runner.missing_currencies() == ["点金石", "崇高", "瓦尔"]


def test_map_missing_currencies_partial() -> None:
    s = Settings()
    s.currency["alch"] = Point(1, 1)
    s.currency["ex"] = Point(2, 2)
    runner = MapRunner(s, BagOrganizer(s))
    assert runner.missing_currencies() == ["瓦尔"]


def test_map_preflight_refuses_when_poe_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("poe2_tools.modules.map_runner.window.is_poe_active", lambda: False)
    s = Settings()
    runner = MapRunner(s, BagOrganizer(s))
    assert runner.preflight() is None
    assert not runner.running
