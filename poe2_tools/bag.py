#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POE2 游玩工具 - 背包整理

- 整理背包：以触发时鼠标位置为第 1 格中心，按住 Ctrl，按配置的行列数依次点击
- 标定：相邻两格中心的水平间距固定（格子宽 = 高），标定一次记录到 ini

坐标体系已确认与 POE1 一致，算法迁移自 poe1_tools/poe_tools/bag.py。
"""

from __future__ import annotations

import random
import time
from collections.abc import Callable, Iterator

import mouse
import pydirectinput

from poe2_tools import common

# ============================================================
# 常量配置
# ============================================================
# 默认行列数（可在 poe2_tools.ini [Bag] Rows / Cols 修改）
DEFAULT_ROWS = 5
DEFAULT_COLS = 11

# 点击间隔随机范围（秒）
MIN_DELAY = 0.03
MAX_DELAY = 0.09

# 鼠标移动耗时随机范围（秒）
MIN_MOVE_DURATION = 0.02
MAX_MOVE_DURATION = 0.12

# 一键存仓默认触发热键（可在 poe2_tools.ini [Bag] DumpHotkey 中修改）
DEFAULT_DUMP_HOTKEY = "f1"


# ============================================================
# 配置读写
# ============================================================
def get_dump_hotkey() -> str:
    """读取一键存仓触发热键，未配置时返回默认值。"""
    config = common.load_config()
    hotkey = config.get("Bag", "DumpHotkey", fallback=DEFAULT_DUMP_HOTKEY).strip()
    return hotkey or DEFAULT_DUMP_HOTKEY


def set_dump_hotkey(hotkey: str) -> None:
    """保存一键存仓触发热键。"""
    config = common.load_config()
    config.set("Bag", "DumpHotkey", hotkey.strip())
    common.save_config(config)


def get_grid_size() -> tuple[int, int]:
    """读取行列数配置，缺失或非法时返回默认值。"""
    config = common.load_config()
    try:
        rows = config.getint("Bag", "Rows", fallback=DEFAULT_ROWS)
        cols = config.getint("Bag", "Cols", fallback=DEFAULT_COLS)
    except ValueError:
        rows, cols = DEFAULT_ROWS, DEFAULT_COLS
    return max(rows, 1), max(cols, 1)


def set_grid_size(rows: int, cols: int) -> None:
    """保存行列数配置。"""
    config = common.load_config()
    config.set("Bag", "Rows", str(max(rows, 1)))
    config.set("Bag", "Cols", str(max(cols, 1)))
    common.save_config(config)


def get_grid_config() -> tuple[float, int, int] | None:
    """
    读取格子配置，返回 (格子间距, 行数, 列数)。
    间距未标定或非法时返回 None；行列数缺失时使用默认值。
    """
    config = common.load_config()
    try:
        cell = float(config.get("Bag", "CellSize", fallback="0"))
    except ValueError:
        return None
    if cell <= 0:
        return None
    rows, cols = get_grid_size()
    return cell, rows, cols


# ============================================================
# 网格坐标计算
# ============================================================
def grid_points(
    origin_x: float, origin_y: float, cell: float, rows: int, cols: int
) -> Iterator[tuple[int, int]]:
    """以 (origin_x, origin_y) 为第 1 格中心，逐格生成中心坐标（按行优先）。"""
    for row in range(rows):
        for col in range(cols):
            yield round(origin_x + col * cell), round(origin_y + row * cell)


# ============================================================
# 标定（记录固定的格子间距）
# ============================================================
# 标定时暂存的第 1 格中心（两次按键在同一会话内完成，无需落盘）
_first_point: tuple[int, int] | None = None


def calibrate_point(index: int, logger: Callable[[str], None] | None = None) -> None:
    """
    记录相邻两格中心，保存固定间距：
    - index=1：暂存当前鼠标位置为左侧格子中心
    - index=2：与左侧格子比较，水平间距写入 [Bag] CellSize
    """
    global _first_point
    if not common.is_poe_active():
        common._emit("请在 Path of Exile 2 窗口前台时进行标定。", logger)
        return

    x, y = mouse.get_position()
    if index == 1:
        _first_point = (int(x), int(y))
        common._emit(f"已记录第 1 格中心: ({int(x)}, {int(y)})，请移到右侧相邻格后按 F4。", logger)
        return

    if _first_point is None:
        common._emit("请先按 F3 记录第 1 格中心。", logger)
        return
    x1, y1 = _first_point
    if x <= x1 or abs(y - y1) > 10:
        common._emit("第 2 格需与第 1 格在同一行且位于其右侧，请重新标定。", logger)
        return

    cell = x - x1
    config = common.load_config()
    config.set("Bag", "CellSize", str(cell))
    common.save_config(config)
    common._emit(f"已保存格子间距: {cell} px（宽 = 高，纵横通用）", logger)


# ============================================================
# 一键存仓
# ============================================================
def dump_bag(logger: Callable[[str], None] | None = None) -> None:
    """
    整理背包：以触发时鼠标位置为第 1 格中心，按住 Ctrl，
    按 ini 配置的 Rows × Cols 依次左键点击每个格子；运行中再次触发则停止。
    """
    with common.running_lock:
        if common.running:
            # 运行中再次按下整理热键：停止整理
            common.stop_event.set()
            return
        if not common.is_poe_active():
            common._emit("未检测到 Path of Exile 2 前台窗口，取消整理。", logger)
            return
        grid = get_grid_config()
        if grid is None:
            common._emit("尚未标定格子间距，请在游戏中用 F3/F4 标定相邻两格。", logger)
            return
        common.running = True
        common.stop_event.clear()

    cell, rows, cols = grid
    origin_x, origin_y = mouse.get_position()
    common._emit(
        f"开始整理：{rows} 行 × {cols} 列，起点 ({origin_x}, {origin_y})，间距 {cell} px",
        logger,
    )

    pydirectinput.keyDown("ctrl")

    try:
        for x, y in grid_points(origin_x, origin_y, cell, rows, cols):
            if common.stop_event.is_set():
                break
            if not common.is_poe_active():
                common.stop_event.set()
                break

            pydirectinput.moveTo(
                x,
                y,
                duration=random.uniform(MIN_MOVE_DURATION, MAX_MOVE_DURATION),
            )
            pydirectinput.click()
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))
    finally:
        common.release_keys()
        with common.running_lock:
            common.running = False
        common.stop_event.clear()
