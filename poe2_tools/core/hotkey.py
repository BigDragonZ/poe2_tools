#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
全局热键管理（keyboard 库）。

keyboard 库不支持「仅某窗口前台时生效」的条件热键，等价做法：
回调内先检查 POE2 是否前台，否则忽略（热键不拦截系统输入，
游戏内其他场景按键行为不受影响）。F12 急停为全局生效。
"""

from __future__ import annotations

import logging
from collections.abc import Callable

import keyboard

logger = logging.getLogger(__name__)


class HotkeyManager:
    """热键注册/注销管理，支持重复注册（先清理旧热键）。"""

    def __init__(self) -> None:
        self._handlers: dict[str, object] = {}

    def register(self, name: str, hotkey: str, callback: Callable[[], None]) -> bool:
        """
        注册全局热键；同名重复注册先移除旧的。
        热键非法时记录日志并返回 False。
        """
        self.unregister(name)
        try:
            self._handlers[name] = keyboard.add_hotkey(hotkey, callback)
            return True
        except Exception as exc:
            logger.warning("热键注册失败 %s (%s): %s", name, hotkey, exc)
            return False

    def register_when_poe_active(
        self,
        name: str,
        hotkey: str,
        callback: Callable[[], None],
        is_active: Callable[[], bool],
    ) -> bool:
        """注册仅 POE2 前台时生效的热键（等价 AHK HotIfWinActive）。"""

        def _guarded() -> None:
            if is_active():
                callback()

        return self.register(name, hotkey, _guarded)

    def unregister(self, name: str) -> None:
        """移除指定热键（不存在时忽略）。"""
        handler = self._handlers.pop(name, None)
        if handler is not None:
            try:
                keyboard.remove_hotkey(handler)
            except Exception:
                pass

    def unregister_all(self) -> None:
        """移除全部热键并解绑 keyboard 钩子。"""
        self._handlers.clear()
        try:
            keyboard.unhook_all()
        except Exception:
            pass
