#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POE2 游玩工具 - 共享基础设施

集中放置各功能模块共用的能力：
- poe2_tools.ini 配置读写（UTF-8 编码，纯 Python 项目无需兼容 AHK）
- POE2 前台窗口检测
- 任务运行状态（stop_event / running）与紧急停止
- 按键释放与日志输出

仅使用输入模拟，不读取游戏内存、不注入、不 Hook。
"""

from __future__ import annotations

import configparser
import ctypes
import threading
from collections.abc import Callable
from pathlib import Path

import pydirectinput

# pydirectinput 默认每次调用后暂停 0.1s，会拖慢整理速度，这里调小
pydirectinput.PAUSE = 0.02

# ============================================================
# 常量配置
# ============================================================
# 配置文件位于项目根目录（本文件在 poe2_tools/ 包内，需向上一级）
INI_PATH = Path(__file__).resolve().parent.parent / "poe2_tools.ini"

# POE2 窗口标题关键字
POE_WINDOW_TITLE = "Path of Exile 2"

# ============================================================
# 全局状态
# ============================================================
stop_event = threading.Event()
running_lock = threading.Lock()
running = False

user32 = ctypes.windll.user32


def _emit(message: str, logger: Callable[[str], None] | None) -> None:
    """向控制台和可选的 logger 同时输出消息。"""
    print(message)
    if logger is not None:
        logger(message)


# ============================================================
# 窗口与焦点辅助
# ============================================================
def get_foreground_window_title() -> str:
    """获取当前前台窗口标题。"""
    try:
        hwnd = user32.GetForegroundWindow()
        length = user32.GetWindowTextLengthW(hwnd)
        if length == 0:
            return ""
        buf = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, buf, length + 1)
        return buf.value
    except Exception:
        return ""


def is_poe_active() -> bool:
    """判断 POE2 窗口是否处于前台。"""
    return POE_WINDOW_TITLE in get_foreground_window_title()


# ============================================================
# 配置文件读写（UTF-8 编码）
# ============================================================
def load_config() -> configparser.ConfigParser:
    """加载 poe2_tools.ini，若不存在则返回空 [Bag] 节。"""
    config = configparser.ConfigParser()
    config.optionxform = str  # 保留键名大小写
    if INI_PATH.exists():
        with open(INI_PATH, "r", encoding="utf-8") as f:
            config.read_file(f)
    if not config.has_section("Bag"):
        config.add_section("Bag")
    return config


def save_config(config: configparser.ConfigParser) -> None:
    """保存配置到 poe2_tools.ini，编码为 UTF-8。"""
    INI_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(INI_PATH, "w", encoding="utf-8") as f:
        config.write(f)


# ============================================================
# 按键释放与紧急中断
# ============================================================
def release_keys() -> None:
    """释放可能被按住的 Ctrl / Shift 与鼠标按键。"""
    pydirectinput.keyUp("ctrl")
    pydirectinput.keyUp("ctrlleft")
    pydirectinput.keyUp("ctrlright")
    pydirectinput.keyUp("shift")
    pydirectinput.keyUp("shiftleft")
    pydirectinput.keyUp("shiftright")
    pydirectinput.mouseUp()
    pydirectinput.mouseUp(button="right")


def emergency_stop(logger: Callable[[str], None] | None = None) -> None:
    """紧急停止：立即停止并释放按键。"""
    _emit("触发紧急停止。", logger)
    stop_event.set()
    release_keys()
