#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连点调度器：到期时间驱动（纯逻辑，可单测）。

等价 AHK 版 CombatScheduler：启动时各连点键首次触发随机错开避免同帧，
每次触发后按「当前时刻 + 抖动间隔」重排下次到期时间，间隔精确不漂移。
调度节拍（10ms）由调用方控制，本类只负责到期计算。
"""

from __future__ import annotations

import random
from collections.abc import Callable

from poe2_tools.config.settings import MIN_INTERVAL_MS
from poe2_tools.core.timing import jitter_ms

# 战斗连点抖动比例（±15%）
JITTER_RATIO = 0.15


class SpamScheduler:
    """多按键连点的到期时间管理。"""

    def __init__(self, rng: Callable[[], float] = random.random) -> None:
        self._rng = rng
        self._next_due: dict[str, float] = {}

    def start(self, intervals_ms: dict[str, int], now: float) -> None:
        """初始化各键首次到期时间：now + rand(0, interval)，错开首帧。"""
        self._next_due = {
            key: now + self._rng() * max(MIN_INTERVAL_MS, interval) / 1000.0
            for key, interval in intervals_ms.items()
        }

    def collect_due(self, now: float) -> list[str]:
        """返回到期按键列表（不修改状态，触发后需调用 reschedule）。"""
        return [key for key, due in self._next_due.items() if now >= due]

    def reschedule(self, key: str, interval_ms: int, random_jitter: bool, now: float) -> None:
        """按键触发后重排下次到期时间（抖动可选，下限 50ms）。"""
        interval = (
            jitter_ms(interval_ms, JITTER_RATIO, self._rng()) if random_jitter else interval_ms
        )
        self._next_due[key] = now + max(MIN_INTERVAL_MS, interval) / 1000.0

    def stop(self) -> None:
        """清空调度状态。"""
        self._next_due = {}
