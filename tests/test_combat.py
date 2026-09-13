#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战斗巡航模块单元测试：按键配置读写与宏启动前置检查。"""

from __future__ import annotations

from pathlib import Path

import pytest

from poe2_tools import combat

from conftest import write_ini


# ============================================================
# 按键配置
# ============================================================
def test_load_skills_defaults() -> None:
    skills = combat.load_skills()
    assert [s.key_id for s in skills] == [key_id for key_id, _ in combat.KEYS]
    by_id = {s.key_id: s for s in skills}
    assert by_id["left"].mode == "spam"  # 默认鼠标左键连点
    assert all(s.mode == "disabled" for k, s in by_id.items() if k != "left")
    assert all(s.interval_ms == combat.DEFAULT_INTERVAL_MS for s in skills)


def test_load_skills_invalid_mode_falls_back(temp_ini: Path) -> None:
    write_ini(temp_ini, "Combat", {"q_mode": "fly"})
    by_id = {s.key_id: s for s in combat.load_skills()}
    assert by_id["q"].mode == "disabled"


def test_load_skills_interval_clamped(temp_ini: Path) -> None:
    write_ini(temp_ini, "Combat", {"q_interval": "10", "w_interval": "abc"})
    by_id = {s.key_id: s for s in combat.load_skills()}
    assert by_id["q"].interval_ms == combat.MIN_INTERVAL_MS
    assert by_id["w"].interval_ms == combat.DEFAULT_INTERVAL_MS


def test_save_load_roundtrip() -> None:
    combat.save_skills(
        [
            combat.SkillConfig("q", "spam", 250),
            combat.SkillConfig("w", "hold", 1000),
        ]
    )
    by_id = {s.key_id: s for s in combat.load_skills()}
    assert by_id["q"].mode == "spam" and by_id["q"].interval_ms == 250
    assert by_id["w"].mode == "hold" and by_id["w"].interval_ms == 1000
    # 未保存的按键保持默认
    assert by_id["e"].mode == "disabled"


# ============================================================
# 启停热键
# ============================================================
def test_toggle_hotkey_default() -> None:
    assert combat.get_toggle_hotkey() == combat.DEFAULT_TOGGLE_HOTKEY


def test_toggle_hotkey_roundtrip() -> None:
    combat.set_toggle_hotkey("f8")
    assert combat.get_toggle_hotkey() == "f8"


# ============================================================
# 宏启动前置检查
# ============================================================
def test_macro_refuses_when_poe_inactive(monkeypatch: pytest.MonkeyPatch) -> None:
    # POE2 不在前台时启动应被拒绝（不依赖测试时的真实前台窗口）
    monkeypatch.setattr(combat.common, "is_poe_active", lambda: False)
    macro = combat.CombatMacro()
    macro.start()
    assert not macro.active
