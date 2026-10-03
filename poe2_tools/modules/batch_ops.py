#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
批量操作核心：背包网格遍历点击（供背包整理/石碑/地图共用）。

等价 AHK 版 RunDump 与 ApplyCurrencyToBag：
- 统一约定：间隔可配置（5-5000ms）+ ±30% 随机抖动
- 修饰键（Ctrl/Shift）在 finally 中释放，任何中断都不残留
- 中断条件：外部停止标记 或 POE2 窗口失焦

坐标全部为客户区坐标，点击时由驱动层换算屏幕坐标。
驱动层可注入，纯逻辑可单测。
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator

from poe2_tools.config.settings import BATCH_JITTER, Point
from poe2_tools.core import input as core_input
from poe2_tools.core import window
from poe2_tools.core.timing import jitter_ms


# ============================================================
# 网格坐标计算（纯逻辑）
# ============================================================
def grid_points(origin: Point, cell: float, rows: int, cols: int) -> Iterator[Point]:
    """以 origin 为第 1 格中心，逐格生成中心坐标（行优先）。"""
    for row in range(rows):
        for col in range(cols):
            yield Point(round(origin.x + col * cell), round(origin.y + row * cell))


# ============================================================
# 点击驱动层
# ============================================================
class BatchDriver:
    """真实驱动：客户区坐标 → 屏幕坐标 → pydirectinput。"""

    def key_down(self, key: str) -> None:
        core_input.key_down(key)

    def key_up(self, key: str) -> None:
        core_input.key_up(key)

    def click_client(self, point: Point, button: str = "LButton") -> None:
        screen = window.client_to_screen(point)
        if screen is not None:
            core_input.click_at(screen.x, screen.y, button)

    def sleep_ms(self, ms: int) -> None:
        time.sleep(ms / 1000.0)


# ============================================================
# 批量操作核心
# ============================================================
def run_dump(
    origin: Point,
    cell: float,
    rows: int,
    cols: int,
    interval_ms: int,
    should_stop: Callable[[], bool],
    is_active: Callable[[], bool],
    driver: BatchDriver,
) -> bool:
    """
    一键存仓核心：Ctrl 按住，以 origin 为第 1 格中心行优先遍历点击。
    返回是否被中断。
    """
    driver.key_down("Ctrl")
    aborted = False
    try:
        for point in grid_points(origin, cell, rows, cols):
            if should_stop() or not is_active():
                aborted = True
                break
            driver.click_client(point)
            driver.sleep_ms(jitter_ms(interval_ms, BATCH_JITTER))
    finally:
        driver.key_up("Ctrl")
    return aborted


def apply_currency_to_bag(
    coord: Point,
    clicks_per_cell: int,
    origin: Point,
    cell: float,
    rows: int,
    cols: int,
    interval_ms: int,
    should_stop: Callable[[], bool],
    is_active: Callable[[], bool],
    driver: BatchDriver,
) -> bool:
    """
    货币批量应用核心：Shift 按住 → 货币坐标右键选中 → 背包逐格左键 clicksPerCell 次。
    返回是否被中断。
    """
    driver.key_down("Shift")
    aborted = False
    try:
        driver.click_client(coord, "RButton")
        driver.sleep_ms(jitter_ms(interval_ms, BATCH_JITTER))
        for point in grid_points(origin, cell, rows, cols):
            if should_stop() or not is_active():
                aborted = True
                break
            for _ in range(clicks_per_cell):
                driver.click_client(point)
                driver.sleep_ms(jitter_ms(interval_ms, BATCH_JITTER))
    finally:
        driver.key_up("Shift")
    return aborted
