#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
战斗宏：多按键连点/按住。

- 10ms 节拍调度循环 + SpamScheduler 到期时间驱动，间隔精确不漂移
- 连点间隔带毫秒级随机附加（0~jitter_ms，每键可配）
- 按住不放键在启动时按下、停止/失焦/急停时全部释放
- 旋风页（active_profile == CYCLONE_PROFILE）：鼠标三键走同一调度
- POE2 窗口失焦自动停止
"""

from __future__ import annotations

import threading
import time

from poe2_tools.config.settings import (
    CYCLONE_PROFILE,
    MODE_HOLD,
    MODE_SPAM,
    KeyConfig,
    Settings,
)
from poe2_tools.core import input as core_input
from poe2_tools.core import window
from poe2_tools.core.scheduler import SpamScheduler
from poe2_tools.modules.base import Logger

# 调度节拍（秒）
LOOP_TICK = 0.01


class CombatMacro:
    """战斗巡航宏。"""

    def __init__(self, settings: Settings, logger: Logger | None = None) -> None:
        self.settings = settings
        self._logger = logger
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._scheduler = SpamScheduler()
        self._held: list[str] = []
        self.active = False

    def log(self, message: str, level: str = "INFO") -> None:
        print(message)
        if self._logger is not None:
            self._logger(message, level)

    # --------------------------------------------------------
    # 启停
    # --------------------------------------------------------
    def toggle(self) -> None:
        """热键入口：运行中 → 停止；空闲 → 启动。"""
        if self.active:
            self.stop()
            self.log("战斗宏已停止")
        else:
            self.start()

    def start(self) -> None:
        """启动战斗宏（后台线程执行）。"""
        with self._lock:
            if self.active:
                return
            if not window.is_poe_active():
                self.log("POE2 窗口未激活，无法启动战斗宏", "WARN")
                return
            keys, cfg = self._current_config()
            enabled = {k: c for k, c in cfg.items() if c.mode != "disabled"}
            if not enabled:
                self.log("所有按键均为禁用状态，请先配置战斗设置", "WARN")
                return

            self._held = []
            for key, c in cfg.items():
                if c.mode == MODE_HOLD:
                    core_input.key_down(key)
                    self._held.append(key)
            self._scheduler.start(
                {k: c.interval_ms for k, c in cfg.items() if c.mode == MODE_SPAM},
                time.monotonic(),
            )
            self.active = True
            self._stop.clear()

        self.log(f"战斗宏已启动（{self._profile_name()}）")
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        """停止战斗宏并释放所有按住键。"""
        self._stop.set()
        for key in self._held:
            core_input.key_up(key)
        self._held = []
        self._scheduler.stop()

    # --------------------------------------------------------
    # 配置
    # --------------------------------------------------------
    def _is_cyclone(self) -> bool:
        return self.settings.combat.active_profile == CYCLONE_PROFILE

    def _profile_name(self) -> str:
        return "旋风" if self._is_cyclone() else f"配置{self.settings.combat.active_profile}"

    def _current_config(self) -> tuple[list[str], dict[str, KeyConfig]]:
        if self._is_cyclone():
            return list(self.settings.combat.cyclone.keys()), self.settings.combat.cyclone
        profile = self.settings.combat.profiles[self.settings.combat.active_profile - 1]
        return list(profile.keys()), profile

    # --------------------------------------------------------
    # 调度主循环
    # --------------------------------------------------------
    def _run(self) -> None:
        _, cfg = self._current_config()
        try:
            while not self._stop.is_set():
                if not window.is_poe_active():
                    self.log("窗口失焦，战斗宏已停止")
                    break
                now = time.monotonic()
                for key in self._scheduler.collect_due(now):
                    c = cfg.get(key)
                    if c is None:
                        continue
                    core_input.press(key)
                    self._scheduler.reschedule(key, c.interval_ms, c.jitter_ms, now)
                self._stop.wait(LOOP_TICK)
        finally:
            self.stop()
            with self._lock:
                self.active = False
