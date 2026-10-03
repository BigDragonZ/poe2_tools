#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开发页：收集开发阶段需要的坐标与范围（客户区坐标）。

左列 6 个测量坐标（点「测量」→ 游戏内 F5 记录光标位置，与坐标模块同流程），
右列 6 个框选范围（点「框选」开启 → 游戏内按住左键拖出矩形松开记录）；
标定/框选流程在 app 控制器中，结果持久化到 ini [Measure] 段。
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from poe2_tools.config.settings import (
    MEASURE_POINT_COUNT,
    MEASURE_RANGE_COUNT,
    Settings,
)

# 页脚说明文字
HELP_TEXT = (
    "测量坐标：点击「测量」，切到游戏将鼠标指向目标后按 F5 记录；再次点击按钮可取消。\n"
    "框选范围：点击「框选」开启，切到游戏按住鼠标左键拖出矩形后松开记录；再次点击按钮可取消。\n"
    "注意：F5 只在本页生效；框选期间左键拖拽会照常作用于游戏（钩子仅旁观记录），请避开游戏内操作。"
)


class DevTab(ttk.Frame):
    """开发页（测量坐标 + 框选范围）。"""

    def __init__(self, master: tk.Misc, on_calibrate: Callable[[str], None]) -> None:
        super().__init__(master, padding=8)
        ttk.Label(
            self,
            text="开发测量：收集开发阶段需要的坐标与范围（客户区坐标，存 ini [Measure] 段）",
            foreground="#64748b",
        ).pack(anchor=tk.W)

        columns = ttk.Frame(self)
        columns.pack(anchor=tk.W, pady=(6, 0))
        self._point_vars: dict[int, tk.StringVar] = {}
        self._range_vars: dict[int, tk.StringVar] = {}
        self._calib_buttons: dict[str, ttk.Button] = {}

        point_frame = ttk.LabelFrame(columns, text="测量坐标", padding=6)
        point_frame.grid(row=0, column=0, sticky=tk.N, padx=(0, 24))
        for i in range(1, MEASURE_POINT_COUNT + 1):
            self._build_row(
                point_frame, i - 1, f"点{i}", f"point{i}", i,
                self._point_vars, on_calibrate,
            )

        range_frame = ttk.LabelFrame(columns, text="框选范围", padding=6)
        range_frame.grid(row=0, column=1, sticky=tk.N)
        for i in range(1, MEASURE_RANGE_COUNT + 1):
            self._build_row(
                range_frame, i - 1, f"范围{i}", f"range{i}", i,
                self._range_vars, on_calibrate,
            )

        ttk.Label(self, text=HELP_TEXT, foreground="#64748b", justify=tk.LEFT).pack(
            anchor=tk.W, pady=(10, 0)
        )

    def _build_row(
        self,
        frame: ttk.Frame,
        row: int,
        label: str,
        target: str,
        index: int,
        var_map: dict[int, tk.StringVar],
        on_calibrate: Callable[[str], None],
    ) -> None:
        """一行测量槽位：名称 + 结果显示 + 标定按钮。target 形如 point1 / range1。"""
        ttk.Label(frame, text=label, width=6).grid(row=row, column=0, sticky=tk.W, pady=2)
        var = tk.StringVar(value="未测量")
        ttk.Label(frame, textvariable=var, width=24, foreground="#38bdf8").grid(
            row=row, column=1, sticky=tk.W, padx=(0, 8), pady=2
        )
        button = ttk.Button(
            frame, text="测量" if target.startswith("point") else "框选", width=6,
            command=lambda t=target: on_calibrate(f"measure:{t}"),
        )
        button.grid(row=row, column=2, pady=2)
        var_map[index] = var
        self._calib_buttons[target] = button

    def refresh(self, settings: Settings) -> None:
        """刷新全部测量结果显示。"""
        for i, var in self._point_vars.items():
            point = settings.dev.measure_points.get(i)
            var.set(f"({point.x}, {point.y})" if point is not None else "未测量")
        for i, var in self._range_vars.items():
            rect = settings.dev.measure_ranges.get(i)
            if rect is None:
                var.set("未框选")
            else:
                x1, y1, x2, y2 = rect
                var.set(f"({x1}, {y1})-({x2}, {y2}) {x2 - x1}×{y2 - y1}")

    def set_pending(self, pending: str | None) -> None:
        """根据待标定目标更新按钮文案（等待 F5/框选时显示「取消」）。"""
        for target, button in self._calib_buttons.items():
            if pending == f"measure:{target}":
                button.config(text="取消")
            else:
                button.config(text="测量" if target.startswith("point") else "框选")
