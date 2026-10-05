#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风重构：确定性有限状态机（FSM）与拾取黑名单（纯逻辑，可单测）。

状态机：IDLE →（toggle）→ TRAVEL（按住左键赶路）⇄ ENGAGE（接敌）/ LOOTING（拾取）
TOWN 为预留状态位（回城开新图二期实现），本期无转移逻辑。

接敌/脱战（Q 层数信号，旋风命中才叠层）：
- TRAVEL 中 Q 层数连续 N 帧 >0 且呈增长 → ENGAGE（进入时若 E 充能可用则按 E）
- ENGAGE 中层数归零且 disengage_timeout_s 内无增长 → TRAVEL

技能释放（TRAVEL/ENGAGE 任意时刻）：
- Q 层数 ≥ q_max_stacks → 按 Q（q_debounce_ms 去抖）
- E 充能 ≥ e_full_charges 且距上次按 E 超过 e_cooldown_s → 按 E

低血喝药（任何运行态，不改变状态）：
- life_ratio < life_threshold 且距上次喝药 ≥ flask_interval_s → 按 flask_key

拾取（拾取优先，同帧同时满足时先拾取）：
- 光标附近拾取黑框 → LOOTING：松左键 → 光标锁定黑框中心（漂移锁）→ 左键单击
  → 消失监听；超时黑框仍在则进黑名单（网格量化 + 有效期），结束回到进入前状态

挂起与急停：
- toggle / 失焦 / 急停：强制压入 IDLE 并清空全部模拟输入（CLEAR_ALL）

时间一律使用秒（time.monotonic 语义），由调用方注入，保证可测。
"""

from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Any


class State(enum.Enum):
    """FSM 状态。"""

    IDLE = "idle"
    TRAVEL = "travel"      # 赶路：按住左键
    ENGAGE = "engage"      # 接敌：层数增长中
    LOOTING = "looting"    # 拾取黑框点击中
    TOWN = "town"          # 预留：回城开新图（二期）


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

    q_stacks: int | None = None                   # Q 层数（未识别为 None）
    e_charges: int | None = None                  # E 充能数字（未识别为 None）
    e_usable: bool = False                        # E 是否为白色可用态（非冷却）
    loot_center: tuple[int, int] | None = None    # 光标附近黑框中心（屏幕绝对坐标）
    life_ratio: float | None = None               # 生命 当前/最大 比值（未识别为 None）


# 技能键位（硬编码 Q/E 格，用户确认 2026-10-05）
DEFAULT_Q_KEY = "q"
DEFAULT_E_KEY = "e"
DEFAULT_FLASK_KEY = "1"


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


class CycloneFSM:
    """旋风状态机：确定性转移 + 严格优先级仲裁（拾取 > 技能 > 接脱战）。"""

    def __init__(
        self,
        loot_cfg: dict[str, Any],
        combat_cfg: dict[str, Any],
        blacklist: Blacklist | None = None,
    ) -> None:
        # 拾取参数
        self._cursor_lock_ms = int(loot_cfg.get("cursor_lock_ms", 30))
        self._pathfinding_timeout_s = int(loot_cfg.get("pathfinding_timeout_ms", 600)) / 1000.0
        self._disappear_min_s = int(loot_cfg.get("disappear_min_ms", 200)) / 1000.0
        self.blacklist = blacklist or Blacklist(
            int(loot_cfg.get("blacklist_grid_px", 32)),
            float(loot_cfg.get("blacklist_cooldown_s", 5)),
        )
        # 战斗参数
        self._engage_frames = int(combat_cfg.get("engage_growth_frames", 2))
        self._disengage_timeout_s = float(combat_cfg.get("disengage_timeout_s", 3.0))
        self._q_max = int(combat_cfg.get("q_max_stacks", 6))
        self._q_debounce_s = int(combat_cfg.get("q_debounce_ms", 500)) / 1000.0
        self._e_full = int(combat_cfg.get("e_full_charges", 3))
        self._e_cooldown_s = float(combat_cfg.get("e_cooldown_s", 4.0))
        self._life_threshold = float(combat_cfg.get("life_threshold", 0.7))
        self._flask_interval_s = float(combat_cfg.get("flask_interval_s", 3.5))
        self._q_key = str(combat_cfg.get("q_key", DEFAULT_Q_KEY))
        self._e_key = str(combat_cfg.get("e_key", DEFAULT_E_KEY))
        self._flask_key = str(combat_cfg.get("flask_key", DEFAULT_FLASK_KEY))

        self.state = State.IDLE
        self._reset_tracking()

    def _reset_tracking(self) -> None:
        """清空帧间跟踪状态（拾取进度保留语义由调用方决定）。"""
        self._loot_target: tuple[int, int] | None = None
        self._loot_since = 0.0
        self._resume_state = State.TRAVEL
        self._prev_stacks: int | None = None
        self._growth_streak = 0
        self._last_growth = 0.0
        self._last_q_press = 0.0
        self._last_e_press = 0.0
        self._last_flask = 0.0

    # ============================================================
    # 模式切换与急停
    # ============================================================
    def toggle(self, now: float) -> list[Action]:
        """F2/侧键切换：IDLE → TRAVEL（按住左键赶路）；运行中 → 强制 IDLE。"""
        if self.state == State.IDLE:
            self._reset_tracking()
            self.state = State.TRAVEL
            return [Action(ActionKind.HOLD_LEFT)]
        return self.force_idle()

    def force_idle(self) -> list[Action]:
        """强制压入 IDLE 并清空全部模拟输入（急停 / 失焦 / toggle 关闭）。"""
        self.state = State.IDLE
        self._reset_tracking()
        # 无论之前是否有模拟输入，都强制补发一次物理 Left Up 并清空队列
        return [Action(ActionKind.CLEAR_ALL)]

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
        if self.state == State.IDLE:
            return []
        # 低血喝药：任何运行态都可触发，不改变状态
        actions = self._check_flask(signals, now)
        if self.state == State.LOOTING:
            return actions + self._step_looting(signals, now)
        return actions + self._step_running(signals, now)

    # --------------------------------------------------------
    # 低血喝药
    # --------------------------------------------------------
    def _check_flask(self, signals: FrameSignals, now: float) -> list[Action]:
        if signals.life_ratio is None or signals.life_ratio >= self._life_threshold:
            return []
        if now - self._last_flask < self._flask_interval_s:
            return []
        self._last_flask = now
        return [Action(ActionKind.PRESS_KEY, key=self._flask_key)]

    # --------------------------------------------------------
    # TRAVEL / ENGAGE 帧逻辑
    # --------------------------------------------------------
    def _step_running(self, signals: FrameSignals, now: float) -> list[Action]:
        # 拾取优先：先判定 LOOTING
        if signals.loot_center is not None:
            x, y = signals.loot_center
            if not self.blacklist.is_blocked(x, y, now):
                self._resume_state = self.state
                self.state = State.LOOTING
                self._loot_target = (x, y)
                self._loot_since = now
                return [
                    Action(ActionKind.RELEASE_LEFT),
                    Action(ActionKind.LOCK_CURSOR, x=x, y=y, duration_ms=self._cursor_lock_ms),
                    Action(ActionKind.CLICK_LEFT),
                ]
        # 更新层数增长跟踪
        self._track_growth(signals, now)
        # 接敌：TRAVEL 中连续 N 帧增长 → ENGAGE（进入时若 E 可用则按 E）
        if self.state == State.TRAVEL and self._growth_streak >= self._engage_frames:
            self.state = State.ENGAGE
            if signals.e_usable and (signals.e_charges or 0) > 0:
                self._last_e_press = now
                return [Action(ActionKind.PRESS_KEY, key=self._e_key)]
            return []
        # Q 满层释放（去抖）
        if (
            signals.q_stacks is not None
            and signals.q_stacks >= self._q_max
            and now - self._last_q_press >= self._q_debounce_s
        ):
            self._last_q_press = now
            return [Action(ActionKind.PRESS_KEY, key=self._q_key)]
        # E 充能回满释放（冷却间隔）
        if (
            signals.e_usable
            and signals.e_charges is not None
            and signals.e_charges >= self._e_full
            and now - self._last_e_press >= self._e_cooldown_s
        ):
            self._last_e_press = now
            return [Action(ActionKind.PRESS_KEY, key=self._e_key)]
        # 脱战：ENGAGE 中层数归零且超时无增长 → TRAVEL（恢复按住左键）
        if (
            self.state == State.ENGAGE
            and signals.q_stacks == 0
            and now - self._last_growth >= self._disengage_timeout_s
        ):
            self.state = State.TRAVEL
            return [Action(ActionKind.HOLD_LEFT)]
        return []

    def _track_growth(self, signals: FrameSignals, now: float) -> None:
        """更新 Q 层数增长跟踪：连续递增才算增长，持平/下降/未识别均打断。"""
        stacks = signals.q_stacks
        if stacks is None:
            self._prev_stacks = None
            self._growth_streak = 0
            return
        if self._prev_stacks is not None and stacks > self._prev_stacks:
            self._growth_streak += 1
            self._last_growth = now
        else:
            self._growth_streak = 0
        self._prev_stacks = stacks

    # --------------------------------------------------------
    # LOOTING 帧逻辑
    # --------------------------------------------------------
    def _step_looting(self, signals: FrameSignals, now: float) -> list[Action]:
        elapsed = now - self._loot_since
        gone = signals.loot_center is None
        # 黑框消失且已过最短监听期 → 拾取成功
        if gone and elapsed >= self._disappear_min_s:
            return self._finish_looting()
        # 超过寻路上限黑框仍在 → 进黑名单后恢复
        if not gone and elapsed > self._pathfinding_timeout_s:
            if self._loot_target is not None:
                self.blacklist.add(*self._loot_target, now)
            return self._finish_looting()
        return []

    def _finish_looting(self) -> list[Action]:
        """拾取结束：回到进入前状态（单击后左键已弹起，恢复按住）。"""
        self._loot_target = None
        self.state = self._resume_state
        return [Action(ActionKind.HOLD_LEFT)]
