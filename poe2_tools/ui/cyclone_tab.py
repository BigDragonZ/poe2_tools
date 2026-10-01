#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风配置页：鼠标三键策略 + Q/E 数字检测标定与截图。

Q/E 坐标标定与模板截图的实际逻辑在 app 控制器中，
本页只负责展示与回调。
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from poe2_tools.config.settings import CYC_DETECT_KEYS, CYC_KEYS, Settings
from poe2_tools.ui.widgets import CYC_NAMES, KeyRowsFrame

# 页脚说明文字
HELP_TEXT = (
    "标定：点击「标定」后切到游戏，将鼠标指向技能图标左上角的数字位置，按 F5 记录；"
    "再次点击按钮可取消。\n"
    "截图：需先标定坐标，在标定点截取模板图（templates/q.png、e.png），提升检测精度。\n"
    "检测每 2 秒一次，数字出现时只按一下对应按键（边沿触发）。"
)


class CycloneTab(ttk.Frame):
    """旋风配置页。"""

    def __init__(
        self,
        master: tk.Misc,
        on_calibrate: Callable[[str], None],
        on_screenshot: Callable[[str], None],
    ) -> None:
        super().__init__(master, padding=8)
        ttk.Label(
            self,
            text="旋风配置：鼠标按键策略 + Q/E 数字检测触发",
            foreground="#64748b",
        ).pack(anchor=tk.W)
        self.rows = KeyRowsFrame(self, CYC_KEYS, CYC_NAMES)
        self.rows.pack(anchor=tk.W, pady=(6, 0))

        detect = ttk.LabelFrame(self, text="Q/E 数字检测", padding=6)
        detect.pack(fill=tk.X, pady=(8, 0))
        self._coord_vars: dict[str, tk.StringVar] = {}
        self._calib_buttons: dict[str, ttk.Button] = {}
        for row, key in enumerate(CYC_DETECT_KEYS):
            ttk.Label(detect, text=f"{key.upper()} 数字检测", width=10).grid(
                row=row, column=0, sticky=tk.W, pady=2
            )
            coord_var = tk.StringVar(value="未标定")
            ttk.Label(detect, textvariable=coord_var, width=14, foreground="#38bdf8").grid(
                row=row, column=1, sticky=tk.W, padx=(0, 8), pady=2
            )
            calib_button = ttk.Button(
                detect, text="标定", width=6,
                command=lambda k=key: on_calibrate(f"cyclone:{k}"),
            )
            calib_button.grid(row=row, column=2, padx=(0, 4), pady=2)
            ttk.Button(
                detect, text="截图", width=6, command=lambda k=key: on_screenshot(k)
            ).grid(row=row, column=3, pady=2)
            self._coord_vars[key] = coord_var
            self._calib_buttons[key] = calib_button

        ttk.Label(self, text=HELP_TEXT, foreground="#64748b", justify=tk.LEFT).pack(
            anchor=tk.W, pady=(10, 0)
        )

    def load_from(self, settings: Settings) -> None:
        """载入鼠标键配置与 Q/E 坐标显示。"""
        self.rows.load_from(settings.cyclone)
        self.refresh_coords(settings)

    def sync_to(self, settings: Settings) -> None:
        """把控件值同步回旋风配置。"""
        self.rows.sync_to(settings.cyclone)

    def refresh_coords(self, settings: Settings) -> None:
        """刷新 Q/E 坐标显示。"""
        for key, var in self._coord_vars.items():
            point = settings.cyclone_coords.get(key)
            var.set(f"({point.x}, {point.y})" if point is not None else "未标定")

    def set_pending(self, pending: str | None) -> None:
        """根据待标定目标更新按钮文案（等待 F5 时显示「取消」）。"""
        for key, button in self._calib_buttons.items():
            button.config(text="取消" if pending == f"cyclone:{key}" else "标定")
