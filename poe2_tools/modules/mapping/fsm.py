#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刷图自动化：确定性有限状态机（FSM）与拾取黑名单（纯逻辑，可单测）。

状态机：IDLE →（侧键切换）→ MOVING ⇄ LOOTING / COMBOS

优先级仲裁（Option B，同帧同时满足时拾取优先）：
  MOVING 态下每帧先判定 LOOTING → 执行拾取动作链 → COMBOS 二次校验
  （拾取期间若 Q 已满则记录 pending，拾取结束后接 COMBOS 动作链）→ 恢复 MOVING。

动作链：
- LOOTING：挂起 MOVING（MouseUp）→ 光标锁定黑框中心 30ms（漂移锁）→ 左键单击
  → 200~600ms 消失监听期；超时黑框仍在则该坐标进黑名单（网格量化，有效期 5s）
- COMBOS：MouseUp → E → 等 e_to_q_delay_ms → Q → 强制 500ms 冷却去抖锁

挂起与急停：
- UI 打开（I / Tab / Esc）挂起 FSM，再按恢复
- 侧键关闭 / 急停 / 窗口失焦：强制压入 IDLE 并清空全部模拟输入

时间一律使用秒（time.monotonic 语义），由调用方注入，保证可测。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class State(enum.Enum):
    """FSM 状态。"""

    IDLE = "idle"
    MOVING = "moving"
    LOOTING = "looting"
    COMBOS = "combos"


class ActionKind(enum.Enum):
    """下发给输入执行线程的动作类型。"""

    HOLD_LEFT = "hold_left"        # 按住左键移动
    RELEASE_LEFT = "release_left"  # MouseUp 挂起移动
    LOCK_CURSOR = "lock_cursor"    # 光标锁定到 (x, y) 持续 duration_ms（漂移锁）
    CLICK_LEFT = "click_left"      # 左键单击
    PRESS_KEY = "press_key"        # 点按键盘 key
    WAIT = "wait"                  # 等待 duration_ms
    CLEAR_ALL = "clear_all"        # 急停清空：补发物理 Left Up 并清空队列


@dataclass(frozen=True)
class Action:
    """一条输入动作指令。"""

    kind: ActionKind
    x: int | None = None
    y: int | None = None
    key: str | None = None
    duration_ms: int = 0


@dataclass(frozen=True)
class FrameSignals:
    """视觉仲裁线程每帧提供给 FSM 的检测信号。"""

    loot_center: tuple[int, int] | None = None  # 光标附近黑框中心（屏幕绝对坐标）
    q_full: bool = False                        # Q 层数是否满 6


# 连招按键（PRD 固定 E → Q）
COMBO_KEY_FIRST = "e"
COMBO_KEY_SECOND = "q"


class Blacklist:
    """
    拾取黑名单：寻路超时的黑框坐标按网格量化后登记，
    有效期内同格不再触发拾取。
    """

    def __init__(self, grid_px: int = 32, cooldown_s: float = 5.0) -> None:
        self._grid = max(1, grid_px)
        self._cooldown = max(0.0, cooldown_s)
        # 量化格 -> 过期时间戳（秒）
        self._entries: dict[tuple[int, int], float] = {}

    def quantize(self, x: int, y: int) -> tuple[int, int]:
        """坐标网格量化：落到所在网格单元。"""
        return (x // self._grid, y // self._grid)

    def add(self, x: int, y: int, now: float) -> None:
        """把绝对坐标加入黑名单。"""
        self._entries[self.quantize(x, y)] = now + self._cooldown

    def is_blocked(self, x: int, y: int, now: float) -> bool:
        """坐标（所在格）是否在黑名单有效期内；顺手清理过期项。"""
        self.purge(now)
        return self.quantize(x, y) in self._entries

    def purge(self, now: float) -> None:
        """清理已过期的黑名单项。"""
        expired = [key for key, expiry in self._entries.items() if expiry <= now]
        for key in expired:
            del self._entries[key]

    def clear(self) -> None:
        self._entries.clear()

    def __len__(self) -> int:
        return len(self._entries)


class MappingFSM:
    """刷图自动化状态机：确定性转移 + 严格优先级仲裁。"""

    def __init__(
        self,
        loot_cfg: dict[str, Any],
        combo_cfg: dict[str, Any],
        blacklist: Blacklist | None = None,
    ) -> None:
        self._cursor_lock_ms = int(loot_cfg.get("cursor_lock_ms", 30))
        self._pathfinding_timeout_s = int(loot_cfg.get("pathfinding_timeout_ms", 600)) / 1000.0
        self._disappear_min_s = int(loot_cfg.get("disappear_min_ms", 200)) / 1000.0
        self._e_to_q_delay_ms = int(combo_cfg.get("e_to_q_delay_ms", 60))
        self._combo_debounce_s = int(combo_cfg.get("combo_debounce_ms", 500)) / 1000.0
        self.blacklist = blacklist or Blacklist(
            int(loot_cfg.get("blacklist_grid_px", 32)),
            float(loot_cfg.get("blacklist_cooldown_s", 5)),
        )
        self.state = State.IDLE
        self._ui_suspended = False
        self._loot_target: tuple[int, int] | None = None
        self._loot_since = 0.0
        self._pending_combo = False
        self._combo_debounce_until = 0.0

    # ============================================================
    # 模式切换与挂起
    # ============================================================
    def toggle(self, now: float) -> list[Action]:
        """侧键切换：IDLE → MOVING（按住左键）；运行中 → 强制 IDLE。"""
        if self.state == State.IDLE:
            self.state = State.MOVING
            self._ui_suspended = False
            return [Action(ActionKind.HOLD_LEFT)]
        return self.force_idle()

    def force_idle(self) -> list[Action]:
        """强制压入 IDLE 并清空全部模拟输入（急停 / 失焦 / 侧键关闭）。"""
        self.state = State.IDLE
        self._ui_suspended = False
        self._loot_target = None
        self._pending_combo = False
        # 无论之前是否有模拟输入，都强制补发一次物理 Left Up 并清空队列
        return [Action(ActionKind.CLEAR_ALL)]

    def set_ui_open(self, ui_open: bool) -> list[Action]:
        """UI 打开挂起 FSM（释放左键），关闭后恢复（MOVING 态重新按住）。"""
        if ui_open == self._ui_suspended:
            return []
        self._ui_suspended = ui_open
        if ui_open:
            return [Action(ActionKind.RELEASE_LEFT)] if self.state != State.IDLE else []
        if self.state == State.MOVING:
            return [Action(ActionKind.HOLD_LEFT)]
        return []

    def set_foreground(self, active: bool) -> list[Action]:
        """前台校验：POE2 非前台时强制压入 IDLE。"""
        if not active:
            return self.force_idle()
        return []

    # ============================================================
    # 每帧仲裁
    # ============================================================
    def step(self, signals: FrameSignals, now: float) -> list[Action]:
        """每帧仲裁入口；返回本帧应执行的动作链（可能为空）。"""
        if self.state == State.IDLE or self._ui_suspended:
            return []
        if self.state == State.MOVING:
            return self._step_moving(signals, now)
        if self.state == State.LOOTING:
            return self._step_looting(signals, now)
        # COMBOS：动作链入态时已一次性下发，本帧恢复 MOVING
        self.state = State.MOVING
        return [Action(ActionKind.HOLD_LEFT)]

    # --------------------------------------------------------
    # 各状态处理
    # --------------------------------------------------------
    def _step_moving(self, signals: FrameSignals, now: float) -> list[Action]:
        # 拾取优先（Option B）：先判定 LOOTING
        if signals.loot_center is not None:
            x, y = signals.loot_center
            if not self.blacklist.is_blocked(x, y, now):
                self.state = State.LOOTING
                self._loot_target = (x, y)
                self._loot_since = now
                # COMBOS 二次校验：同帧 Q 已满则拾取结束后接连招
                self._pending_combo = signals.q_full and now >= self._combo_debounce_until
                return [
                    Action(ActionKind.RELEASE_LEFT),
                    Action(ActionKind.LOCK_CURSOR, x=x, y=y, duration_ms=self._cursor_lock_ms),
                    Action(ActionKind.CLICK_LEFT),
                ]
        if signals.q_full and now >= self._combo_debounce_until:
            return self._enter_combos(now)
        return []

    def _step_looting(self, signals: FrameSignals, now: float) -> list[Action]:
        elapsed = now - self._loot_since
        gone = signals.loot_center is None
        # 黑框消失且已过最短监听期 → 拾取成功
        if gone and elapsed >= self._disappear_min_s:
            return self._finish_looting(now)
        # 超过寻路上限黑框仍在 → 进黑名单后恢复移动
        if not gone and elapsed > self._pathfinding_timeout_s:
            if self._loot_target is not None:
                self.blacklist.add(*self._loot_target, now)
            return self._finish_looting(now)
        return []

    def _finish_looting(self, now: float) -> list[Action]:
        """拾取结束：有待接连招则进 COMBOS，否则恢复 MOVING。"""
        self._loot_target = None
        if self._pending_combo:
            self._pending_combo = False
            return self._enter_combos(now)
        self.state = State.MOVING
        return [Action(ActionKind.HOLD_LEFT)]

    def _enter_combos(self, now: float) -> list[Action]:
        """COMBOS 动作链：MouseUp → E → 延时 → Q；强制冷却去抖锁。"""
        self.state = State.COMBOS
        self._combo_debounce_until = now + self._combo_debounce_s
        return [
            Action(ActionKind.RELEASE_LEFT),
            Action(ActionKind.PRESS_KEY, key=COMBO_KEY_FIRST),
            Action(ActionKind.WAIT, duration_ms=self._e_to_q_delay_ms),
            Action(ActionKind.PRESS_KEY, key=COMBO_KEY_SECOND),
        ]
