#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POE2 窗口绑定与客户区坐标换算。

所有标定坐标均为 POE2 客户区坐标（与 AHK CoordMode Client 一致），
而 pydirectinput 使用屏幕绝对坐标，本模块负责两者的换算，
并提供前台检测、最小化检测供自动挂起机制使用。

仅使用 Win32 user32 API（ctypes），不读取游戏内存、不注入、不 Hook。
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes

from poe2_tools.config.settings import POE_WINDOW_TITLE, Point

user32 = ctypes.windll.user32


def _find_poe_hwnd() -> int:
    """按标题关键字查找 POE2 窗口句柄，未找到返回 0。"""
    found = wintypes.HWND(0)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def _enum(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if POE_WINDOW_TITLE in buf.value:
                nonlocal found
                found = hwnd
                return False
        return True

    user32.EnumWindows(_enum, 0)
    return found  # type: ignore[return-value]


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


def is_poe_minimized() -> bool:
    """判断 POE2 窗口是否已最小化（窗口不存在时返回 True，视为不可用）。"""
    hwnd = _find_poe_hwnd()
    if not hwnd:
        return True
    return bool(user32.IsIconic(hwnd))


def client_origin() -> Point | None:
    """POE2 客户区左上角的屏幕坐标；窗口不存在时返回 None。"""
    hwnd = _find_poe_hwnd()
    if not hwnd:
        return None
    point = wintypes.POINT(0, 0)
    if not user32.ClientToScreen(hwnd, ctypes.byref(point)):
        return None
    return Point(point.x, point.y)


def client_size() -> Point | None:
    """POE2 客户区宽高（x=宽, y=高）；窗口不存在时返回 None。"""
    hwnd = _find_poe_hwnd()
    if not hwnd:
        return None
    rect = wintypes.RECT()
    if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
        return None
    return Point(rect.right - rect.left, rect.bottom - rect.top)


def client_to_screen(p: Point) -> Point | None:
    """客户区坐标 → 屏幕坐标；窗口不存在时返回 None。"""
    origin = client_origin()
    if origin is None:
        return None
    return Point(origin.x + p.x, origin.y + p.y)


def cursor_client_pos() -> Point | None:
    """当前鼠标位置（客户区坐标）；窗口不存在时返回 None。"""
    hwnd = _find_poe_hwnd()
    if not hwnd:
        return None
    point = wintypes.POINT()
    if not user32.GetCursorPos(ctypes.byref(point)):
        return None
    if not user32.ScreenToClient(hwnd, ctypes.byref(point)):
        return None
    return Point(point.x, point.y)
