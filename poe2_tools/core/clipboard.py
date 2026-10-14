#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
系统剪贴板读写（win32clipboard，懒导入）。

游戏内 Ctrl+C 复制物品文本的配套工具：写入哨兵值 → 触发复制 → 读取，
读取结果仍为哨兵值说明目标格子无物品（或复制失败）。
OpenClipboard 在系统剪贴板被占用时会失败，统一带重试。
"""

from __future__ import annotations

import time

_OPEN_RETRIES = 10
_OPEN_RETRY_INTERVAL_S = 0.05


def _open_clipboard() -> None:
    """带重试地打开剪贴板（被其他程序占用时稍候重试）。"""
    import win32clipboard  # noqa: PLC0415 懒导入，仅桌面环境需要

    for attempt in range(_OPEN_RETRIES):
        try:
            win32clipboard.OpenClipboard()
            return
        except Exception:
            if attempt == _OPEN_RETRIES - 1:
                raise
            time.sleep(_OPEN_RETRY_INTERVAL_S)


def read_clipboard() -> str | None:
    """读取系统剪贴板 Unicode 文本；非文本内容返回 None。"""
    import win32clipboard  # noqa: PLC0415
    import win32con  # noqa: PLC0415

    _open_clipboard()
    try:
        if win32clipboard.IsClipboardFormatAvailable(win32con.CF_UNICODETEXT):
            return win32clipboard.GetClipboardData(win32con.CF_UNICODETEXT)
        return None
    finally:
        win32clipboard.CloseClipboard()


def write_clipboard(text: str) -> None:
    """把字符串写入系统剪贴板（Unicode），覆盖旧内容。"""
    import win32clipboard  # noqa: PLC0415
    import win32con  # noqa: PLC0415

    _open_clipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(win32con.CF_UNICODETEXT, text)
    finally:
        win32clipboard.CloseClipboard()
