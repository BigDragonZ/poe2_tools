#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通货市场抓取的 UI 原子操作驱动。

封装最底层的界面交互：剪贴板写入、带修饰键的坐标点击、输入框粘贴、
区域截屏。坐标一律为客户区坐标，内部换算屏幕坐标。

安全约定：
- 任何按住修饰键（Ctrl）的操作都用 try/finally 保证释放，避免按键粘连
- 点击后追加 click_delay（±30% 抖动），保留人工操作痕迹
- win32clipboard/mss/PIL 懒导入，纯逻辑路径不依赖桌面环境
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from poe2_tools.config.settings import BATCH_JITTER, Point
from poe2_tools.core import input as core_input
from poe2_tools.core import window
from poe2_tools.core.timing import jitter_ms

if TYPE_CHECKING:
    from PIL import Image


class DriverError(Exception):
    """驱动层失败（中文原因，直接展示给用户）。"""


def copy_to_clipboard(text: str) -> None:
    """把字符串写入系统剪贴板（Unicode）。"""
    import win32clipboard  # noqa: PLC0415 懒导入，仅桌面环境需要

    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    finally:
        win32clipboard.CloseClipboard()


class UIActionDriver:
    """市场界面基础操作驱动。click_delay_ms 为每次点击后的等待（毫秒）。"""

    def __init__(self, click_delay_ms: int = 150) -> None:
        self._click_delay_ms = click_delay_ms

    # --------------------------------------------------------
    # 延时
    # --------------------------------------------------------
    def sleep_ms(self, ms: int) -> None:
        """按毫秒等待，带 ±30% 随机抖动（保留人工操作痕迹）。"""
        if ms <= 0:
            return
        time.sleep(jitter_ms(ms, BATCH_JITTER) / 1000)

    def _after_click(self) -> None:
        self.sleep_ms(self._click_delay_ms)

    # --------------------------------------------------------
    # 坐标点击（可带修饰键）
    # --------------------------------------------------------
    def click_position(self, point: Point, modifier: str | None = None) -> None:
        """
        移动并点击客户区坐标点。modifier 为 "Ctrl"/"Alt"/"Shift" 时先按住修饰键，
        点击后在 finally 中释放，保证按下/释放配对。
        """
        screen = window.client_to_screen(point)
        if screen is None:
            raise DriverError("未找到 POE2 窗口，无法换算屏幕坐标")
        if modifier is None:
            core_input.click_at(screen.x, screen.y)
            self._after_click()
            return
        core_input.key_down(modifier)
        try:
            core_input.click_at(screen.x, screen.y)
        finally:
            core_input.key_up(modifier)
        self._after_click()

    # --------------------------------------------------------
    # 输入框粘贴
    # --------------------------------------------------------
    def input_from_clipboard(self, point: Point) -> None:
        """点击输入框 → Ctrl+A 全选清空 → Ctrl+V 粘贴剪贴板内容。"""
        self.click_position(point)
        core_input.key_down("Ctrl")
        try:
            core_input.press("a")
            self.sleep_ms(50)
            core_input.press("v")
        finally:
            core_input.key_up("Ctrl")
        self._after_click()

    # --------------------------------------------------------
    # 区域截屏
    # --------------------------------------------------------
    def capture_region(self, rect: tuple[int, int, int, int]) -> "Image.Image":
        """对客户区范围 (x1, y1, x2, y2) 截屏，返回 PIL Image。"""
        import mss  # noqa: PLC0415 懒导入
        from PIL import Image  # noqa: PLC0415 懒导入

        origin = window.client_origin()
        if origin is None:
            raise DriverError("未找到 POE2 窗口，无法换算屏幕坐标")
        x1, y1, x2, y2 = rect
        monitor = {
            "left": origin.x + x1,
            "top": origin.y + y1,
            "width": x2 - x1,
            "height": y2 - y1,
        }
        with mss.mss() as sct:
            shot = sct.grab(monitor)
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")
