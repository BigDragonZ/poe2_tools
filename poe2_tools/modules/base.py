#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
业务模块共享基类：热键切换式批量任务（启动/停止/失焦中断）。

统一行为：
- 运行中再次触发热键 → 置停止标记
- 启动前检查 POE2 前台，触发时鼠标位置（客户区坐标）= 背包第 1 格中心
- 工作线程结束/中断后复位状态
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from poe2_tools.config.settings import Point, Settings
from poe2_tools.core import window

Logger = Callable[[str, str], None]  # (消息, 级别)；级别默认 INFO，bus.log 兼容


class ToggleRunner:
    """热键切换式任务基类。子类实现 preflight 与 _work。"""

    name = "任务"

    def __init__(self, settings: Settings, logger: Logger | None = None) -> None:
        self.settings = settings
        self._logger = logger
        self._running = False
        self._stop = False
        self._lock = threading.Lock()

    @property
    def running(self) -> bool:
        return self._running

    def log(self, message: str, level: str = "INFO") -> None:
        print(message)
        if self._logger is not None:
            self._logger(message, level)

    def toggle(self) -> None:
        """热键入口：运行中 → 停止；空闲 → 启动。"""
        with self._lock:
            if self._running:
                self._stop = True
                self.log(f"正在停止{self.name}...")
                return
        origin = self.preflight()
        if origin is None:
            return
        with self._lock:
            self._running = True
            self._stop = False
        threading.Thread(target=self._run, args=(origin,), daemon=True).start()

    def request_stop(self) -> None:
        """外部急停：置停止标记（工作线程在下一次点击前中断）。"""
        self._stop = True

    # --------------------------------------------------------
    # 子类实现
    # --------------------------------------------------------
    def preflight(self) -> Point | None:
        """启动前检查，返回背包第 1 格中心（客户区坐标）；不满足条件返回 None。"""
        raise NotImplementedError

    def _work(self, origin: Point) -> None:
        """工作线程主体。"""
        raise NotImplementedError

    # --------------------------------------------------------
    # 内部
    # --------------------------------------------------------
    def _should_stop(self) -> bool:
        return self._stop

    def _run(self, origin: Point) -> None:
        try:
            self._work(origin)
        finally:
            with self._lock:
                self._running = False
                self._stop = False

    def _check_common(self) -> Point | None:
        """公共检查：POE2 前台 + 已标定格距 + 取鼠标位置。"""
        if not window.is_poe_active():
            return None
        if self.settings.general.sort.cell_size <= 0:
            self.log("请先用 F3/F4 标定背包格子间距", "WARN")
            return None
        origin = window.cursor_client_pos()
        if origin is None:
            self.log("未找到 POE2 窗口", "ERROR")
            return None
        return origin
