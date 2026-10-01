#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
键鼠模拟封装（pydirectinput / DirectInput 扫描码）。

- 按键命名沿用 AHK 风格（LButton/RButton/MButton/Space/q/w/...），
  由本层映射到 pydirectinput 调用，业务层不感知底层库
- 坐标一律使用屏幕绝对坐标；客户区坐标请先在 core.window 换算
- 维护按住键台账，紧急停止时保证全部释放
"""

from __future__ import annotations

import threading

import pydirectinput

# pydirectinput 默认每次调用后暂停 0.1s，会拖慢批量操作，这里调小
pydirectinput.PAUSE = 0.01
# 禁用故障安全（鼠标甩到角落抛异常），急停场景下可能误触发
pydirectinput.FAILSAFE = False

# 鼠标按键：AHK 名 -> pydirectinput button 名
_MOUSE_BUTTONS = {"LButton": "left", "RButton": "right", "MButton": "middle"}
# 键盘按键：AHK 名 -> pydirectinput key 名
_KEYBOARD_KEYS = {
    "Space": "space",
    "Ctrl": "ctrl",
    "Shift": "shift",
    "Alt": "alt",
}

# 急停时必须释放的按键（修饰键 + 鼠标键）
EMERGENCY_RELEASE_KEYS = ["Ctrl", "Shift", "Alt", "LButton", "RButton", "MButton"]

# 当前按住的按键台账（线程安全）
_held_lock = threading.Lock()
_held_keys: list[str] = []


def _to_driver_name(key: str) -> str:
    """键盘按键名映射：单字符直接用，其余查表。"""
    if key in _KEYBOARD_KEYS:
        return _KEYBOARD_KEYS[key]
    return key.lower()


def press(key: str) -> None:
    """点按一次（鼠标键 = 点击，键盘键 = 按下并释放）。"""
    if key in _MOUSE_BUTTONS:
        pydirectinput.click(button=_MOUSE_BUTTONS[key])
    else:
        pydirectinput.press(_to_driver_name(key))


def key_down(key: str) -> None:
    """按住按键并登记台账。"""
    if key in _MOUSE_BUTTONS:
        pydirectinput.mouseDown(button=_MOUSE_BUTTONS[key])
    else:
        pydirectinput.keyDown(_to_driver_name(key))
    with _held_lock:
        if key not in _held_keys:
            _held_keys.append(key)


def key_up(key: str) -> None:
    """释放按键并移出台账（未按住时静默忽略异常）。"""
    try:
        if key in _MOUSE_BUTTONS:
            pydirectinput.mouseUp(button=_MOUSE_BUTTONS[key])
        else:
            pydirectinput.keyUp(_to_driver_name(key))
    except Exception:
        pass
    with _held_lock:
        if key in _held_keys:
            _held_keys.remove(key)


def held_keys() -> list[str]:
    """当前台账中按住的按键。"""
    with _held_lock:
        return list(_held_keys)


def move_to(x: int, y: int) -> None:
    """鼠标瞬间移动到屏幕坐标（批量操作用，不做拟人化轨迹）。"""
    pydirectinput.moveTo(x, y)


def click_at(x: int, y: int, button: str = "LButton") -> None:
    """移动到屏幕坐标并点击。"""
    move_to(x, y)
    press(button)


def release_all(extra_keys: list[str] | None = None) -> None:
    """
    释放台账 + 急停清单中的所有按键。
    任何可能卡住的按键操作都必须走这里兜底。
    """
    targets = set(EMERGENCY_RELEASE_KEYS)
    targets.update(held_keys())
    if extra_keys:
        targets.update(extra_keys)
    for key in targets:
        key_up(key)
