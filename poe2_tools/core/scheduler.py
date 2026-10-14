#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
连点调度器：到期时间驱动（纯逻辑，可单测）。

启动时各连点键首次触发随机错开避免同帧，每次触发后按
「当前时刻 + 间隔 + 0~jitter_ms 随机附加」重排下次到期时间，
间隔精确不漂移。抖动为毫秒级绝对值（非比例），保留人工操作痕迹。
调度节拍（10ms）由调用方控制，本类只负责到期计算。

core 不依赖 config：最小间隔由调用方注入（与 config.MIN_INTERVAL_MS 同源，
ui/app 启动时以配置值构造），本模块保持纯逻辑可单测。
"""

from __future__ import annotations

import random
from collections.abc import Callable

# 缺省最小间隔（ms），与 config.settings.MIN_INTERVAL_MS 保持一致；
# 调用方应传配置值覆盖，直接使用时行为不变
DEFAULT_MIN_INTERVAL_MS = 50


class SpamScheduler:
    """多按键连点的到期时间管理。"""

    def __init__(
        self,
        min_interval_ms: int = DEFAULT_MIN_INTERVAL_MS,
        rng: Callable[[], float] = random.random,
    ) -> None:
        self._min_interval_ms = max(1, min_interval_ms)
        self._rng = rng
        self._next_due: dict[str, float] = {}

    def start(self, intervals_ms: dict[str, int], now: float) -> None:
        """初始化各键首次到期时间：now + rand(0, interval)，错开首帧。"""
        self._next_due = {
            key: now + self._rng() * max(self._min_interval_ms, interval) / 1000.0
            for key, interval in intervals_ms.items()
        }

    def collect_due(self, now: float) -> list[str]:
        """返回到期按键列表（不修改状态，触发后需调用 reschedule）。"""
        return [key for key, due in self._next_due.items() if now >= due]

    def reschedule(self, key: str, interval_ms: int, jitter_ms: int, now: float) -> None:
        """
        按键触发后重排下次到期时间：
        间隔 + 0~jitter_ms 随机附加（jitter_ms 为 0 时不抖动），下限为构造时注入的最小间隔。
        """
        interval = interval_ms + round(self._rng() * jitter_ms)
        self._next_due[key] = now + max(self._min_interval_ms, interval) / 1000.0

    def stop(self) -> None:
        """清空调度状态。"""
        self._next_due = {}
