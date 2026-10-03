#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
侧键识别工具：依次按下两个鼠标侧键，程序告诉你各自是什么。

运行：uv run python -m poe2_tools.modules.mapping.check_buttons

流程：
1. 提示「请按第一个侧键」→ 按下后立刻报告它是什么键
2. 提示「请按第二个侧键」→ 按下后报告，并给出结论汇总

mouse 库钩子与 Win32 轮询双通道同时监听，任一通道识别到即算
（同一物理按键的双通道重复上报会被去抖忽略）。按 Esc 放弃退出。
"""

from __future__ import annotations

import ctypes
import threading
import time

# Win32 虚拟键码：XButton1 / XButton2
VK_XBUTTON1 = 0x05
VK_XBUTTON2 = 0x06

# 轮询间隔（秒）
_POLL_TICK = 0.01

# 记录一次后忽略后续事件的冷却（秒）：吸收同一物理按键的双通道重复上报
_COOLDOWN_S = 0.6

_stop = threading.Event()
_step = 0            # 0 = 等待第一个，1 = 等待第二个，2 = 已完成
_results: list[str] = []
_cooldown_until = 0.0
_lock = threading.Lock()


def _record(source: str, label: str) -> None:
    """记录一次侧键按下（去抖 + 按步骤推进）。"""
    global _step, _cooldown_until
    with _lock:
        if _step >= 2 or time.monotonic() < _cooldown_until:
            return
        _cooldown_until = time.monotonic() + _COOLDOWN_S
        _results.append(label)
        order = "第一个" if _step == 0 else "第二个"
        print(f"✔ 你按的{order}侧键是：{label}（{source} 通道识别）")
        _step += 1
        if _step == 1:
            print("\n请按第二个侧键…")
        else:
            _summary()


def _summary() -> None:
    first, second = _results
    print("\n========== 结论 ==========")
    print(f"第一个侧键 = {first}")
    print(f"第二个侧键 = {second}")
    print("（mouse 库命名：x = XButton1，x2 = XButton2；刷图配置 toggle_button 用该名字）")
    print("==========================")
    _stop.set()


def _on_mouse_event(event: object) -> None:
    """通道 A：mouse 库钩子（只取按下事件）。"""
    import mouse  # noqa: PLC0415

    if isinstance(event, mouse.ButtonEvent) and event.event_type == "down":
        _record("mouse钩子", str(event.button))


def _poll_loop() -> None:
    """通道 B：GetAsyncKeyState 轮询两个侧键的按下边沿。"""
    user32 = ctypes.windll.user32
    prev = {VK_XBUTTON1: False, VK_XBUTTON2: False}
    names = {VK_XBUTTON1: "XButton1（mouse 库名 x）", VK_XBUTTON2: "XButton2（mouse 库名 x2）"}
    while not _stop.is_set():
        for vk in (VK_XBUTTON1, VK_XBUTTON2):
            down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
            if down and not prev[vk]:
                _record("Win32轮询", names[vk])
            prev[vk] = down
        time.sleep(_POLL_TICK)


def main() -> None:
    import keyboard  # noqa: PLC0415
    import mouse  # noqa: PLC0415

    print(__doc__)
    print("监听已启动。请按第一个侧键…\n")
    mouse.hook(_on_mouse_event)
    thread = threading.Thread(target=_poll_loop, daemon=True)
    thread.start()
    try:
        while not _stop.is_set():
            if keyboard.is_pressed("esc"):
                print("\n已放弃退出。")
                break
            time.sleep(0.05)
    finally:
        _stop.set()
        mouse.unhook_all()


if __name__ == "__main__":
    main()
