#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
坐标页：10 种货币坐标标定。

左列为三级货币（蜕变/增幅/富豪/崇高/混沌），右列为普通货币
（点金石/瓦尔/磨刀石/护甲片/奥术师）；标定逻辑在 app 控制器中。
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from poe2_tools.config.settings import CURRENCY_KEYS, CURRENCY_NAMES, TIERED_KEYS, Settings

# 页脚说明文字
HELP_TEXT = (
    "标定方法：点击货币所在行的「标定」，切到游戏将鼠标指向仓库中对应货币图标中心，"
    "按 F5 记录；再次点击按钮可取消。\n"
    "蜕变/增幅/富豪/崇高/混沌为三级货币，只需标定一级坐标："
    "二级 = 一级 +70px，三级 = +140px（向右偏移）。"
)


class CoordsTab(ttk.Frame):
    """货币坐标标定页。"""

    def __init__(self, master: tk.Misc, on_calibrate: Callable[[str], None]) -> None:
        super().__init__(master, padding=8)
        ttk.Label(
            self,
            text="货币坐标：石碑/地图速点依赖此处标定（客户区坐标）",
            foreground="#64748b",
        ).pack(anchor=tk.W)

        columns = ttk.Frame(self)
        columns.pack(anchor=tk.W, pady=(6, 0))
        self._coord_vars: dict[str, tk.StringVar] = {}
        self._calib_buttons: dict[str, ttk.Button] = {}

        normal_keys = [key for key in CURRENCY_KEYS if key not in TIERED_KEYS]
        for col, keys in enumerate((TIERED_KEYS, normal_keys)):
            frame = ttk.Frame(columns)
            frame.grid(row=0, column=col, sticky=tk.N, padx=(0, 24))
            for row, key in enumerate(keys):
                ttk.Label(frame, text=CURRENCY_NAMES[key], width=8).grid(
                    row=row, column=0, sticky=tk.W, pady=2
                )
                coord_var = tk.StringVar(value="未标定")
                ttk.Label(frame, textvariable=coord_var, width=12, foreground="#38bdf8").grid(
                    row=row, column=1, sticky=tk.W, padx=(0, 8), pady=2
                )
                button = ttk.Button(
                    frame, text="标定", width=6,
                    command=lambda k=key: on_calibrate(f"currency:{k}"),
                )
                button.grid(row=row, column=2, pady=2)
                self._coord_vars[key] = coord_var
                self._calib_buttons[key] = button

        ttk.Label(self, text=HELP_TEXT, foreground="#64748b", justify=tk.LEFT).pack(
            anchor=tk.W, pady=(10, 0)
        )

    def refresh_coords(self, settings: Settings) -> None:
        """刷新全部货币坐标显示。"""
        for key, var in self._coord_vars.items():
            point = settings.currency.get(key)
            var.set(f"({point.x}, {point.y})" if point is not None else "未标定")

    def set_pending(self, pending: str | None) -> None:
        """根据待标定目标更新按钮文案（等待 F5 时显示「取消」）。"""
        for key, button in self._calib_buttons.items():
            button.config(text="取消" if pending == f"currency:{key}" else "标定")
