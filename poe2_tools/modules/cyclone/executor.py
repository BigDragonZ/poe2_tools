#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风输入执行线程：SendInput 动作队列 + 拟人化 jitter + 漂移锁 + 急停清空。

- 按键注入走 Win32 SendInput（扫描码模式，游戏兼容性最好）。
  pywin32 未封装 SendInput 本体，故用 ctypes 调 user32.SendInput，
  常量优先取自 win32con（pywin32），不可用时回落到内置值。
- 每次注入前 5~15ms 均匀 jitter；按键 down→up 时长随机 15~35ms；
  组合键间隙（WAIT 动作）±5ms 正态抖动。
- 任何按住操作都在 stop()/急停路径释放；CLEAR_ALL 动作先清空队列
  再补发一次物理 Left Up。
"""

from __future__ import annotations

import ctypes
import logging
import queue
import random
import threading
import time
from ctypes import wintypes

from poe2_tools.modules.cyclone.fsm import Action, ActionKind

logger = logging.getLogger(__name__)

# win32con 常量（pywin32 提供；不可用时用内置等价值）
try:
    import win32con

    _KEYEVENTF_SCANCODE = win32con.KEYEVENTF_SCANCODE
    _KEYEVENTF_KEYUP = win32con.KEYEVENTF_KEYUP
    _MOUSEEVENTF_LEFTDOWN = win32con.MOUSEEVENTF_LEFTDOWN
    _MOUSEEVENTF_LEFTUP = win32con.MOUSEEVENTF_LEFTUP
except ImportError:  # pragma: no cover - 非 Windows 环境兜底
    _KEYEVENTF_SCANCODE = 0x0008
    _KEYEVENTF_KEYUP = 0x0002
    _MOUSEEVENTF_LEFTDOWN = 0x0002
    _MOUSEEVENTF_LEFTUP = 0x0004

# 拟人化抖动参数（毫秒）
INJECT_JITTER_MIN_MS = 5
INJECT_JITTER_MAX_MS = 15
HOLD_MIN_MS = 15
HOLD_MAX_MS = 35
COMBO_GAP_SIGMA_MS = 5

_user32 = getattr(ctypes, "windll", None)
if _user32 is not None:
    _user32 = _user32.user32
# 非 Windows 环境（纯逻辑测试）下为 None，执行原语调用前检查


# ============================================================
# SendInput 结构体
# ============================================================
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.POINTER(wintypes.ULONG)),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", _MOUSEINPUT), ("ki", _KEYBDINPUT)]


class _INPUT(ctypes.Structure):
    _fields_ = [("type", wintypes.DWORD), ("union", _INPUT_UNION)]


_INPUT_MOUSE = 0
_INPUT_KEYBOARD = 1


def _send(inputs: list[_INPUT]) -> None:
    """批量提交 SendInput。"""
    count = len(inputs)
    array_type = _INPUT * count
    _user32.SendInput(count, array_type(*inputs), ctypes.sizeof(_INPUT))


def _scan_code(key: str) -> int:
    """字符键 → 扫描码（MapVirtualKeyW）。"""
    vk = ord(key.upper())
    return int(_user32.MapVirtualKeyW(vk, 0))


def _key_input(scan: int, flags: int) -> _INPUT:
    item = _INPUT()
    item.type = _INPUT_KEYBOARD
    item.union.ki = _KEYBDINPUT(0, scan, flags, 0, None)
    return item


def _mouse_input(flags: int) -> _INPUT:
    item = _INPUT()
    item.type = _INPUT_MOUSE
    item.union.mi = _MOUSEINPUT(0, 0, 0, flags, 0, None)
    return item


# ============================================================
# 输入执行线程
# ============================================================
class InputExecutor:
    """动作队列消费者：单线程顺序执行 FSM 下发的动作链。"""

    def __init__(self, rng: random.Random | None = None) -> None:
        self._rng = rng or random.Random()
        self._queue: queue.Queue[Action] = queue.Queue()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._left_held = False

    # --------------------------------------------------------
    # 生命周期
    # --------------------------------------------------------
    def start(self) -> None:
        """启动执行线程（幂等）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止线程并释放所有按住的键。"""
        self._stop.set()
        self.clear()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            self._thread = None

    # --------------------------------------------------------
    # 队列操作
    # --------------------------------------------------------
    def submit(self, actions: list[Action]) -> None:
        """下发动作链；含 CLEAR_ALL 时先清空队列（急停语义）。"""
        if any(a.kind == ActionKind.CLEAR_ALL for a in actions):
            self._drain_queue()
            self._release_left()
            return
        for action in actions:
            self._queue.put(action)

    def clear(self) -> None:
        """急停清空：清空队列并补发物理 Left Up。"""
        self._drain_queue()
        self._release_left()

    def _drain_queue(self) -> None:
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                return

    # --------------------------------------------------------
    # 执行主循环
    # --------------------------------------------------------
    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                try:
                    action = self._queue.get(timeout=0.05)
                except queue.Empty:
                    continue
                try:
                    self._execute(action)
                except Exception as exc:  # noqa: BLE001 单条失败不拖垮线程
                    logger.warning("输入执行异常 %s: %s", action.kind.value, exc)
        finally:
            self._release_left()

    def _execute(self, action: Action) -> None:
        kind = action.kind
        if kind == ActionKind.WAIT:
            # 组合键间隙：±5ms 正态抖动，下限 1ms
            gap = action.duration_ms + self._rng.gauss(0, COMBO_GAP_SIGMA_MS)
            time.sleep(max(1.0, gap) / 1000.0)
            return
        # 每次注入前的拟人化 jitter
        self._sleep_jitter(INJECT_JITTER_MIN_MS, INJECT_JITTER_MAX_MS)
        if kind == ActionKind.HOLD_LEFT:
            self._press_left()
        elif kind == ActionKind.RELEASE_LEFT:
            self._release_left()
        elif kind == ActionKind.CLICK_LEFT:
            self._click_left()
        elif kind == ActionKind.PRESS_KEY:
            self._press_key(action.key or "")
        elif kind == ActionKind.LOCK_CURSOR:
            self._lock_cursor(action.x or 0, action.y or 0, action.duration_ms)
        elif kind == ActionKind.CLEAR_ALL:
            self._drain_queue()
            self._release_left()

    def _sleep_jitter(self, lo_ms: int, hi_ms: int) -> None:
        time.sleep(self._rng.uniform(lo_ms, hi_ms) / 1000.0)

    # --------------------------------------------------------
    # 物理输入原语（按住键台账保证 finally 可释放）
    # --------------------------------------------------------
    def _press_left(self) -> None:
        if self._left_held:
            return
        _send([_mouse_input(_MOUSEEVENTF_LEFTDOWN)])
        self._left_held = True

    def _release_left(self) -> None:
        # 无论台账如何都补发物理 Left Up，保证急停可靠
        try:
            _send([_mouse_input(_MOUSEEVENTF_LEFTUP)])
        finally:
            self._left_held = False

    def _click_left(self) -> None:
        _send([_mouse_input(_MOUSEEVENTF_LEFTDOWN)])
        self._sleep_jitter(HOLD_MIN_MS, HOLD_MAX_MS)
        _send([_mouse_input(_MOUSEEVENTF_LEFTUP)])
        self._left_held = False

    def _press_key(self, key: str) -> None:
        if not key:
            return
        scan = _scan_code(key)
        _send([_key_input(scan, _KEYEVENTF_SCANCODE)])
        self._sleep_jitter(HOLD_MIN_MS, HOLD_MAX_MS)
        _send([_key_input(scan, _KEYEVENTF_SCANCODE | _KEYEVENTF_KEYUP)])

    def _lock_cursor(self, x: int, y: int, duration_ms: int) -> None:
        """光标漂移锁：锁定到黑框中心并短暂停留。"""
        _user32.SetCursorPos(int(x), int(y))
        time.sleep(max(0, duration_ms) / 1000.0)
