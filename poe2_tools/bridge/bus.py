#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
进程内事件总线：模块 → UI / WebSocket 的解耦通道。

消息为 dict，JSON 可序列化，契约见 docs/architecture.md：
- {"type": "log",    "message": "..."}
- {"type": "status", "payload": {"foreground": bool, "combat": "running|stopped",
                                  "bag": "...", "waystone": "...", "map": "..."}}
- {"type": "event",  "name": "calibrated|aborted|error", "detail": "..."}
- {"type": "command", "action": "...", "params": {...}}（外部 → 工具，仅 WebSocket 入口）
"""

from __future__ import annotations

import threading
from collections.abc import Callable

Message = dict
Subscriber = Callable[[Message], None]


class EventBus:
    """线程安全的发布/订阅总线。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: list[Subscriber] = []

    def subscribe(self, fn: Subscriber) -> None:
        """订阅消息；返回的退订通过 unsubscribe。"""
        with self._lock:
            self._subscribers.append(fn)

    def unsubscribe(self, fn: Subscriber) -> None:
        with self._lock:
            if fn in self._subscribers:
                self._subscribers.remove(fn)

    def publish(self, message: Message) -> None:
        """发布消息；单个订阅者异常不影响其他订阅者。"""
        with self._lock:
            subscribers = list(self._subscribers)
        for fn in subscribers:
            try:
                fn(message)
            except Exception:
                pass

    # --------------------------------------------------------
    # 便捷发布
    # --------------------------------------------------------
    def log(self, message: str) -> None:
        self.publish({"type": "log", "message": message})

    def status(self, payload: dict) -> None:
        self.publish({"type": "status", "payload": payload})

    def event(self, name: str, detail: str = "") -> None:
        self.publish({"type": "event", "name": name, "detail": detail})


# 全局总线实例：桌面工具为单进程应用，模块与 UI 共享
bus = EventBus()
