#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""旋风 FSM 单元测试：接敌/脱战、满层放 Q、E 满充能释放、拾取优先、低血喝药、急停。"""

from __future__ import annotations

from poe2_tools.modules.cyclone.fsm import (
    Action,
    ActionKind,
    CycloneFSM,
    FrameSignals,
    State,
)

# 测试用 loot/combat 配置（与模块默认值一致）
LOOT_CFG = {
    "cursor_lock_ms": 30,
    "pathfinding_timeout_ms": 600,
    "disappear_min_ms": 200,
    "blacklist_grid_px": 32,
    "blacklist_cooldown_s": 5,
}
COMBAT_CFG = {
    "engage_growth_frames": 2,
    "disengage_timeout_s": 3.0,
    "q_max_stacks": 6,
    "q_debounce_ms": 500,
    "e_full_charges": 3,
    "e_cooldown_s": 4.0,
    "life_threshold": 0.7,
    "flask_interval_s": 3.5,
    "q_key": "q",
    "e_key": "e",
    "flask_key": "1",
}


def make_fsm() -> CycloneFSM:
    return CycloneFSM(LOOT_CFG, COMBAT_CFG)


def kinds(actions: list[Action]) -> list[ActionKind]:
    return [a.kind for a in actions]


def sig(**kwargs) -> FrameSignals:
    return FrameSignals(**kwargs)


# ============================================================
# toggle / 急停
# ============================================================
def test_toggle_idle_to_travel_holds_left():
    fsm = make_fsm()
    actions = fsm.toggle(100.0)
    assert fsm.state == State.TRAVEL
    assert kinds(actions) == [ActionKind.HOLD_LEFT]


def test_toggle_running_forces_idle_clear_all():
    fsm = make_fsm()
    fsm.toggle(100.0)
    actions = fsm.toggle(101.0)
    assert fsm.state == State.IDLE
    assert kinds(actions) == [ActionKind.CLEAR_ALL]


def test_force_idle_clears_all():
    fsm = make_fsm()
    fsm.toggle(100.0)
    actions = fsm.force_idle()
    assert fsm.state == State.IDLE
    assert kinds(actions) == [ActionKind.CLEAR_ALL]


def test_set_foreground_inactive_forces_idle():
    fsm = make_fsm()
    fsm.toggle(100.0)
    actions = fsm.set_foreground(False)
    assert fsm.state == State.IDLE
    assert kinds(actions) == [ActionKind.CLEAR_ALL]
    # 恢复前台不自动重启
    assert fsm.set_foreground(True) == []
    assert fsm.state == State.IDLE


def test_idle_step_no_actions():
    fsm = make_fsm()
    assert fsm.step(sig(q_stacks=6, loot_center=(100, 100), life_ratio=0.1), 100.0) == []


def test_town_state_reserved():
    assert State.TOWN.value == "town"


# ============================================================
# 接敌 / 脱战
# ============================================================
def test_engage_after_two_growth_frames():
    fsm = make_fsm()
    fsm.toggle(100.0)
    assert fsm.step(sig(q_stacks=0), 100.0) == []
    assert fsm.step(sig(q_stacks=1), 100.5) == []  # 第 1 帧增长
    actions = fsm.step(sig(q_stacks=2), 101.0)     # 第 2 帧连续增长 → 接敌
    assert fsm.state == State.ENGAGE
    assert actions == []  # e_usable=False 时进入不按 E


def test_engage_presses_e_when_usable():
    fsm = make_fsm()
    fsm.toggle(100.0)
    fsm.step(sig(q_stacks=0), 100.0)
    fsm.step(sig(q_stacks=1), 100.5)
    actions = fsm.step(sig(q_stacks=2, e_charges=2, e_usable=True), 101.0)
    assert fsm.state == State.ENGAGE
    assert actions == [Action(ActionKind.PRESS_KEY, key="e")]


def test_growth_streak_broken_by_plateau():
    fsm = make_fsm()
    fsm.toggle(100.0)
    fsm.step(sig(q_stacks=0), 100.0)
    fsm.step(sig(q_stacks=1), 100.5)  # 增长 1
    fsm.step(sig(q_stacks=1), 101.0)  # 持平打断
    fsm.step(sig(q_stacks=2), 101.5)  # 重新计 1
    assert fsm.state == State.TRAVEL
    fsm.step(sig(q_stacks=3), 102.0)  # 连续第 2 帧
    assert fsm.state == State.ENGAGE


def test_growth_streak_broken_by_unrecognized_frame():
    fsm = make_fsm()
    fsm.toggle(100.0)
    fsm.step(sig(q_stacks=0), 100.0)
    fsm.step(sig(q_stacks=1), 100.5)
    fsm.step(sig(q_stacks=None), 101.0)  # 未识别打断
    fsm.step(sig(q_stacks=2), 101.5)
    assert fsm.state == State.TRAVEL


def test_disengage_after_zero_stacks_and_timeout():
    fsm = make_fsm()
    fsm.toggle(100.0)
    fsm.step(sig(q_stacks=0), 100.0)
    fsm.step(sig(q_stacks=1), 100.5)
    fsm.step(sig(q_stacks=2), 101.0)
    assert fsm.state == State.ENGAGE
    # 层数归零但 3 秒内 → 仍 ENGAGE
    assert fsm.step(sig(q_stacks=0), 102.0) == []
    assert fsm.state == State.ENGAGE
    # 距上次增长超过 3 秒 → 脱战回 TRAVEL 并恢复按住左键
    actions = fsm.step(sig(q_stacks=0), 104.6)
    assert fsm.state == State.TRAVEL
    assert kinds(actions) == [ActionKind.HOLD_LEFT]


def test_no_disengage_while_growth_continues():
    fsm = make_fsm()
    fsm.toggle(100.0)
    fsm.step(sig(q_stacks=0), 100.0)
    fsm.step(sig(q_stacks=1), 100.5)
    fsm.step(sig(q_stacks=2), 101.0)
    assert fsm.state == State.ENGAGE
    # 层数短暂归 0 但随后继续增长（新一波怪）
    fsm.step(sig(q_stacks=0), 103.0)
    fsm.step(sig(q_stacks=1), 103.5)  # 增长刷新计时
    assert fsm.step(sig(q_stacks=0), 104.0) == []
    assert fsm.state == State.ENGAGE


# ============================================================
# Q 满层释放（去抖）
# ============================================================
def test_q_full_presses_q_with_debounce():
    fsm = make_fsm()
    fsm.toggle(100.0)
    actions = fsm.step(sig(q_stacks=6), 100.1)
    assert actions == [Action(ActionKind.PRESS_KEY, key="q")]
    # 500ms 去抖内不重复释放
    assert fsm.step(sig(q_stacks=6), 100.4) == []
    # 去抖过后可再次释放
    actions = fsm.step(sig(q_stacks=6), 100.7)
    assert actions == [Action(ActionKind.PRESS_KEY, key="q")]


def test_q_below_max_no_press():
    fsm = make_fsm()
    fsm.toggle(100.0)
    assert fsm.step(sig(q_stacks=5), 100.1) == []


# ============================================================
# E 满充能释放（冷却间隔）
# ============================================================
def test_e_full_presses_e_with_cooldown():
    fsm = make_fsm()
    fsm.toggle(100.0)
    actions = fsm.step(sig(q_stacks=0, e_charges=3, e_usable=True), 100.1)
    assert actions == [Action(ActionKind.PRESS_KEY, key="e")]
    # 冷却 4s 内不重复
    assert fsm.step(sig(q_stacks=0, e_charges=3, e_usable=True), 102.0) == []
    # 冷却过后再放
    actions = fsm.step(sig(q_stacks=0, e_charges=3, e_usable=True), 104.2)
    assert actions == [Action(ActionKind.PRESS_KEY, key="e")]


def test_e_dark_state_not_fired():
    """暗色冷却态（e_usable=False）即使数字为 3 也不放 E。"""
    fsm = make_fsm()
    fsm.toggle(100.0)
    assert fsm.step(sig(q_stacks=0, e_charges=3, e_usable=False), 100.1) == []


def test_e_below_full_not_fired():
    fsm = make_fsm()
    fsm.toggle(100.0)
    assert fsm.step(sig(q_stacks=0, e_charges=2, e_usable=True), 100.1) == []


# ============================================================
# 拾取（优先级与黑名单）
# ============================================================
def test_loot_priority_over_q_full():
    """同帧 Q 满 + 拾取黑框：拾取优先，Q 留到后续帧。"""
    fsm = make_fsm()
    fsm.toggle(100.0)
    actions = fsm.step(sig(q_stacks=6, loot_center=(500, 600)), 100.1)
    assert fsm.state == State.LOOTING
    assert kinds(actions) == [
        ActionKind.RELEASE_LEFT,
        ActionKind.LOCK_CURSOR,
        ActionKind.CLICK_LEFT,
    ]
    assert actions[1].x == 500 and actions[1].y == 600
    assert actions[1].duration_ms == 30


def test_looting_finish_returns_to_travel_and_reholds():
    fsm = make_fsm()
    fsm.toggle(100.0)
    fsm.step(sig(loot_center=(500, 600)), 100.1)
    assert fsm.state == State.LOOTING
    # 黑框消失但未到最短监听期 → 无动作
    assert fsm.step(sig(), 100.2) == []
    # 过监听期 → 拾取成功，回 TRAVEL 恢复按住左键
    actions = fsm.step(sig(), 100.4)
    assert fsm.state == State.TRAVEL
    assert kinds(actions) == [ActionKind.HOLD_LEFT]


def test_looting_returns_to_engage():
    fsm = make_fsm()
    fsm.toggle(100.0)
    fsm.step(sig(q_stacks=0), 100.0)
    fsm.step(sig(q_stacks=1), 100.2)
    fsm.step(sig(q_stacks=2), 100.4)
    assert fsm.state == State.ENGAGE
    fsm.step(sig(q_stacks=2, loot_center=(500, 600)), 100.6)
    assert fsm.state == State.LOOTING
    actions = fsm.step(sig(q_stacks=2), 100.9)
    assert fsm.state == State.ENGAGE
    assert kinds(actions) == [ActionKind.HOLD_LEFT]


def test_looting_timeout_blacklists_target():
    fsm = make_fsm()
    fsm.toggle(100.0)
    fsm.step(sig(loot_center=(500, 600)), 100.0)
    assert fsm.state == State.LOOTING
    # 黑框 600ms 后仍在 → 进黑名单并恢复
    actions = fsm.step(sig(loot_center=(500, 600)), 100.7)
    assert fsm.state == State.TRAVEL
    assert kinds(actions) == [ActionKind.HOLD_LEFT]
    assert fsm.blacklist.is_blocked(500, 600, 100.7)
    # 黑名单有效期内同格不再触发拾取（505/605 与 500/600 同属 32px 网格 (15,18)）
    assert fsm.step(sig(loot_center=(505, 605)), 101.0) == []
    # 过期后可再次拾取
    actions = fsm.step(sig(loot_center=(505, 605)), 106.0)
    assert fsm.state == State.LOOTING
    assert kinds(actions)[0] == ActionKind.RELEASE_LEFT


# ============================================================
# 低血喝药
# ============================================================
def test_low_life_presses_flask_with_interval():
    fsm = make_fsm()
    fsm.toggle(100.0)
    actions = fsm.step(sig(life_ratio=0.5), 100.1)
    assert actions == [Action(ActionKind.PRESS_KEY, key="1")]
    # 最小间隔 3.5s 内不重复
    assert fsm.step(sig(life_ratio=0.5), 101.0) == []
    # 间隔过后再喝
    actions = fsm.step(sig(life_ratio=0.5), 103.7)
    assert actions == [Action(ActionKind.PRESS_KEY, key="1")]


def test_flask_does_not_change_state():
    fsm = make_fsm()
    fsm.toggle(100.0)
    fsm.step(sig(q_stacks=0), 100.0)
    fsm.step(sig(q_stacks=1), 100.2)
    fsm.step(sig(q_stacks=2), 100.4)
    assert fsm.state == State.ENGAGE
    actions = fsm.step(sig(q_stacks=3, life_ratio=0.3), 100.6)
    assert fsm.state == State.ENGAGE
    assert actions == [Action(ActionKind.PRESS_KEY, key="1")]


def test_flask_not_triggered_above_threshold():
    fsm = make_fsm()
    fsm.toggle(100.0)
    assert fsm.step(sig(life_ratio=0.7), 100.1) == []
    assert fsm.step(sig(life_ratio=0.9), 100.2) == []


def test_flask_during_looting():
    """拾取中低血也要喝药（不改变 LOOTING 流程）。"""
    fsm = make_fsm()
    fsm.toggle(100.0)
    fsm.step(sig(loot_center=(500, 600)), 100.0)
    assert fsm.state == State.LOOTING
    actions = fsm.step(sig(loot_center=(500, 600), life_ratio=0.2), 100.2)
    assert fsm.state == State.LOOTING
    assert Action(ActionKind.PRESS_KEY, key="1") in actions
