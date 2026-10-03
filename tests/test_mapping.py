#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷图自动化纯逻辑单元测试：config 合并、黑名单、FSM 仲裁。"""

from __future__ import annotations

import json
from pathlib import Path

from poe2_tools.modules.mapping.config import DEFAULT_CONFIG, load_config, save_config
from poe2_tools.modules.mapping.fsm import (
    Action,
    ActionKind,
    Blacklist,
    FrameSignals,
    MappingFSM,
    State,
)

LOOT_CFG = DEFAULT_CONFIG["loot"]
COMBO_CFG = DEFAULT_CONFIG["combos"]


def make_fsm() -> MappingFSM:
    return MappingFSM(dict(LOOT_CFG), dict(COMBO_CFG))


def kinds(actions: list[Action]) -> list[ActionKind]:
    return [a.kind for a in actions]


# ============================================================
# config 加载：默认值合并 / 自定义路径
# ============================================================
def test_config_defaults_when_file_missing(tmp_path: Path) -> None:
    cfg = load_config(tmp_path / "不存在.json")
    assert cfg == DEFAULT_CONFIG


def test_config_corrupt_file_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{不是合法 json", encoding="utf-8")
    assert load_config(path) == DEFAULT_CONFIG


def test_config_deep_merge_partial_override(tmp_path: Path) -> None:
    path = tmp_path / "custom.json"
    path.write_text(json.dumps({"loot": {"roi_size": 200}}), encoding="utf-8")
    cfg = load_config(path)
    assert cfg["loot"]["roi_size"] == 200  # 覆盖生效
    assert cfg["loot"]["black_v_max"] == 40  # 缺字段回落默认
    assert cfg["system"]["resolution"] == [2560, 1440]
    assert cfg["combos"]["combo_debounce_ms"] == 500


def test_config_type_mismatch_falls_back(tmp_path: Path) -> None:
    path = tmp_path / "wrong_type.json"
    path.write_text(json.dumps({"loot": {"roi_size": "很大"}}), encoding="utf-8")
    cfg = load_config(path)
    assert cfg["loot"]["roi_size"] == 150


def test_config_save_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "out.json"
    save_config({"combos": {"match_confidence": 0.9}}, path)
    cfg = load_config(path)
    assert cfg["combos"]["match_confidence"] == 0.9
    assert cfg["system"]["capture_fps"] == 60


def test_config_default_path_loads_bundled_file() -> None:
    # 模块自带 config.json 应与内置默认值一致
    assert load_config() == DEFAULT_CONFIG


# ============================================================
# 黑名单：坐标量化 / 有效期过期
# ============================================================
def test_blacklist_quantize() -> None:
    bl = Blacklist(grid_px=32, cooldown_s=5)
    assert bl.quantize(0, 0) == (0, 0)
    assert bl.quantize(31, 31) == (0, 0)
    assert bl.quantize(32, 63) == (1, 1)
    assert bl.quantize(2500, 1400) == (78, 43)


def test_blacklist_blocked_within_cooldown_and_same_cell() -> None:
    bl = Blacklist(grid_px=32, cooldown_s=5)
    bl.add(100, 100, now=0.0)
    assert bl.is_blocked(100, 100, 1.0)
    assert bl.is_blocked(110, 120, 1.0)  # 同格量化
    assert not bl.is_blocked(200, 100, 1.0)  # 不同格


def test_blacklist_expires() -> None:
    bl = Blacklist(grid_px=32, cooldown_s=5)
    bl.add(100, 100, now=0.0)
    assert bl.is_blocked(100, 100, 4.9)
    assert not bl.is_blocked(100, 100, 5.1)
    assert len(bl) == 0  # 过期项被清理


# ============================================================
# FSM：模式切换 / 急停 / UI 挂起
# ============================================================
def test_fsm_toggle_enters_moving_and_holds_left() -> None:
    fsm = make_fsm()
    actions = fsm.toggle(now=0.0)
    assert fsm.state == State.MOVING
    assert kinds(actions) == [ActionKind.HOLD_LEFT]


def test_fsm_toggle_off_forces_idle_and_clears() -> None:
    fsm = make_fsm()
    fsm.toggle(now=0.0)
    actions = fsm.toggle(now=1.0)
    assert fsm.state == State.IDLE
    assert kinds(actions) == [ActionKind.CLEAR_ALL]


def test_fsm_idle_step_is_silent() -> None:
    fsm = make_fsm()
    signals = FrameSignals(loot_center=(100, 100), q_full=True)
    assert fsm.step(signals, now=0.0) == []


def test_fsm_foreground_lost_forces_idle() -> None:
    fsm = make_fsm()
    fsm.toggle(now=0.0)
    actions = fsm.set_foreground(False)
    assert fsm.state == State.IDLE
    assert kinds(actions) == [ActionKind.CLEAR_ALL]
    # 恢复前台不会自动回 MOVING，需侧键重新开启
    assert fsm.set_foreground(True) == []
    assert fsm.state == State.IDLE


def test_fsm_ui_suspend_and_resume() -> None:
    fsm = make_fsm()
    fsm.toggle(now=0.0)
    actions = fsm.set_ui_open(True)
    assert kinds(actions) == [ActionKind.RELEASE_LEFT]
    # 挂起期间不仲裁
    signals = FrameSignals(loot_center=(100, 100), q_full=True)
    assert fsm.step(signals, now=0.1) == []
    assert fsm.state == State.MOVING
    # 恢复后重新按住左键
    assert kinds(fsm.set_ui_open(False)) == [ActionKind.HOLD_LEFT]
    # 重复设置同一状态不重复下发
    assert fsm.set_ui_open(False) == []


# ============================================================
# FSM：LOOTING 动作链与消失监听
# ============================================================
def test_fsm_loot_chain() -> None:
    fsm = make_fsm()
    fsm.toggle(now=0.0)
    actions = fsm.step(FrameSignals(loot_center=(500, 600)), now=0.1)
    assert fsm.state == State.LOOTING
    assert kinds(actions) == [
        ActionKind.RELEASE_LEFT,
        ActionKind.LOCK_CURSOR,
        ActionKind.CLICK_LEFT,
    ]
    lock = actions[1]
    assert (lock.x, lock.y) == (500, 600)
    assert lock.duration_ms == 30


def test_fsm_loot_success_resumes_moving_after_min_watch() -> None:
    fsm = make_fsm()
    fsm.toggle(now=0.0)
    fsm.step(FrameSignals(loot_center=(500, 600)), now=0.0)
    # 消失监听期下限 200ms：100ms 时黑框消失 → 继续观察
    assert fsm.step(FrameSignals(), now=0.1) == []
    assert fsm.state == State.LOOTING
    # 250ms 时黑框消失 → 拾取成功，恢复 MOVING
    actions = fsm.step(FrameSignals(), now=0.25)
    assert fsm.state == State.MOVING
    assert kinds(actions) == [ActionKind.HOLD_LEFT]


def test_fsm_loot_timeout_blacklists_and_resumes() -> None:
    fsm = make_fsm()
    fsm.toggle(now=0.0)
    fsm.step(FrameSignals(loot_center=(500, 600)), now=0.0)
    # 600ms 内黑框仍在 → 继续监听
    assert fsm.step(FrameSignals(loot_center=(500, 600)), now=0.6) == []
    # 超过 600ms → 进黑名单并恢复 MOVING
    actions = fsm.step(FrameSignals(loot_center=(500, 600)), now=0.7)
    assert fsm.state == State.MOVING
    assert kinds(actions) == [ActionKind.HOLD_LEFT]
    assert fsm.blacklist.is_blocked(500, 600, 0.7)
    # 黑名单有效期内不再触发拾取
    assert fsm.step(FrameSignals(loot_center=(500, 600)), now=1.0) == []
    assert fsm.state == State.MOVING
    # 过期后可再次拾取
    actions = fsm.step(FrameSignals(loot_center=(500, 600)), now=6.0)
    assert fsm.state == State.LOOTING
    assert ActionKind.CLICK_LEFT in kinds(actions)


# ============================================================
# FSM：COMBOS 动作链与冷却去抖
# ============================================================
def test_fsm_combo_chain_and_debounce() -> None:
    fsm = make_fsm()
    fsm.toggle(now=0.0)
    actions = fsm.step(FrameSignals(q_full=True), now=1.0)
    assert fsm.state == State.COMBOS
    assert kinds(actions) == [
        ActionKind.RELEASE_LEFT,
        ActionKind.PRESS_KEY,
        ActionKind.WAIT,
        ActionKind.PRESS_KEY,
    ]
    assert actions[1].key == "e"
    assert actions[2].duration_ms == 60
    assert actions[3].key == "q"
    # 下一帧恢复 MOVING
    assert kinds(fsm.step(FrameSignals(q_full=True), now=1.1)) == [ActionKind.HOLD_LEFT]
    assert fsm.state == State.MOVING
    # 500ms 冷却去抖锁内 Q 仍满 → 不再触发
    assert fsm.step(FrameSignals(q_full=True), now=1.4) == []
    # 冷却结束后可再次触发
    actions = fsm.step(FrameSignals(q_full=True), now=1.6)
    assert ActionKind.PRESS_KEY in kinds(actions)


def test_fsm_priority_loot_over_combo_same_frame() -> None:
    """同帧双触发：LOOTING 优先，COMBOS 在拾取结束后接招。"""
    fsm = make_fsm()
    fsm.toggle(now=0.0)
    both = FrameSignals(loot_center=(500, 600), q_full=True)
    actions = fsm.step(both, now=0.0)
    assert fsm.state == State.LOOTING
    assert ActionKind.CLICK_LEFT in kinds(actions)
    # 拾取完成（黑框消失）→ 直接进 COMBOS 而非恢复 MOVING
    actions = fsm.step(FrameSignals(), now=0.3)
    assert fsm.state == State.COMBOS
    assert kinds(actions) == [
        ActionKind.RELEASE_LEFT,
        ActionKind.PRESS_KEY,
        ActionKind.WAIT,
        ActionKind.PRESS_KEY,
    ]
    # COMBOS 结束恢复 MOVING
    assert kinds(fsm.step(FrameSignals(), now=0.4)) == [ActionKind.HOLD_LEFT]


def test_fsm_combo_not_pending_when_q_not_full_during_loot() -> None:
    """拾取期间 Q 未满：拾取结束直接恢复 MOVING。"""
    fsm = make_fsm()
    fsm.toggle(now=0.0)
    fsm.step(FrameSignals(loot_center=(500, 600), q_full=False), now=0.0)
    actions = fsm.step(FrameSignals(), now=0.3)
    assert fsm.state == State.MOVING
    assert kinds(actions) == [ActionKind.HOLD_LEFT]
