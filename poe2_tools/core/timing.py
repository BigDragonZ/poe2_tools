#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
时间规约：随机抖动与范围夹取（纯逻辑，可单测）。

与 AHK 版一致的约定：
- 战斗连点：±15% 抖动，下限 50ms
- 批量操作：±30% 抖动，范围 5-5000ms
抖动保留人工操作痕迹，避免机械化特征。
"""

from __future__ import annotations

import random


def jitter_ms(base_ms: int, ratio: float, rng: float | None = None) -> int:
    """
    间隔 ±ratio 随机抖动，等价 AHK Jitter()：
    round(base * (1 - ratio + rand(0, 2*ratio)))。
    rng 可注入 [0, 1) 的随机数用于测试。
    """
    r = random.random() if rng is None else rng
    return round(base_ms * (1 - ratio + r * 2 * ratio))


def clamp(value: int, lo: int, hi: int) -> int:
    """把数值夹取到 [lo, hi] 区间。"""
    return max(lo, min(hi, value))
