#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
右侧功能设置区：热键 + 背包/石碑/地图参数 + 保存按钮。

只负责控件展示与值同步；保存后的热键重注册等逻辑在 app 控制器中。
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from poe2_tools.config.settings import (
    CURRENCY_KEYS,
    CURRENCY_NAMES,
    MAX_BATCH_INTERVAL_MS,
    MIN_BATCH_INTERVAL_MS,
    Settings,
)
from poe2_tools.ui.widgets import clamp, parse_int

# 石碑级别显示名 <-> 数值
TIER_LABELS = {1: "一级", 2: "二级", 3: "三级"}
LABEL_TO_TIER = {label: tier for tier, label in TIER_LABELS.items()}


class SettingsPanel(ttk.LabelFrame):
    """功能设置面板。"""

    def __init__(self, master: tk.Misc, on_save: Callable[[], None]) -> None:
        super().__init__(master, text="功能设置", padding=8)

        self.combat_hotkey_var = tk.StringVar()
        self.dump_hotkey_var = tk.StringVar()
        self.way_hotkey_var = tk.StringVar()
        self.map_hotkey_var = tk.StringVar()
        self.rows_var = tk.StringVar()
        self.cols_var = tk.StringVar()
        self.dump_interval_var = tk.StringVar()
        self.way_currency_var = tk.StringVar()
        self.way_tier_var = tk.StringVar()
        self.way_interval_var = tk.StringVar()
        self.map_interval_var = tk.StringVar()
        self.cell_var = tk.StringVar(value="未标定")

        row = 0
        row = self._entry_row(row, "战斗宏热键", self.combat_hotkey_var)
        row = self._entry_row(row, "整理热键", self.dump_hotkey_var)
        row = self._entry_row(row, "石碑速点热键", self.way_hotkey_var)
        row = self._entry_row(row, "地图速点热键", self.map_hotkey_var)
        ttk.Separator(self, orient=tk.HORIZONTAL).grid(
            row=row, column=0, columnspan=2, sticky=tk.EW, pady=6
        )
        row += 1
        row = self._entry_row(row, "行数", self.rows_var)
        row = self._entry_row(row, "列数", self.cols_var)
        row = self._entry_row(row, "整理间隔(ms)", self.dump_interval_var)

        ttk.Label(self, text="石碑货币").grid(row=row, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(
            self,
            textvariable=self.way_currency_var,
            values=[CURRENCY_NAMES[key] for key in CURRENCY_KEYS],
            state="readonly",
            width=10,
        ).grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1

        ttk.Label(self, text="石碑级别").grid(row=row, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(
            self,
            textvariable=self.way_tier_var,
            values=list(LABEL_TO_TIER.keys()),
            state="readonly",
            width=10,
        ).grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1

        row = self._entry_row(row, "石碑间隔(ms)", self.way_interval_var)
        row = self._entry_row(row, "地图间隔(ms)", self.map_interval_var)

        ttk.Label(self, text="格子间距").grid(row=row, column=0, sticky=tk.W, pady=2)
        ttk.Label(self, textvariable=self.cell_var, foreground="#38bdf8").grid(
            row=row, column=1, sticky=tk.W, pady=2
        )
        row += 1

        ttk.Button(self, text="保存配置", command=on_save).grid(
            row=row, column=0, columnspan=2, sticky=tk.EW, pady=(10, 0)
        )
        self.columnconfigure(1, weight=1)

    def _entry_row(self, row: int, label: str, var: tk.StringVar) -> int:
        """添加一行「标签 + 输入框」，返回下一行号。"""
        ttk.Label(self, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
        ttk.Entry(self, textvariable=var, width=12).grid(row=row, column=1, sticky=tk.W, pady=2)
        return row + 1

    # --------------------------------------------------------
    # 值同步
    # --------------------------------------------------------
    def load_from(self, settings: Settings) -> None:
        """把配置写入控件。"""
        self.combat_hotkey_var.set(settings.combat_hotkey)
        self.dump_hotkey_var.set(settings.dump_hotkey)
        self.way_hotkey_var.set(settings.way_hotkey)
        self.map_hotkey_var.set(settings.map_hotkey)
        self.rows_var.set(str(settings.rows))
        self.cols_var.set(str(settings.cols))
        self.dump_interval_var.set(str(settings.dump_interval_ms))
        self.way_currency_var.set(CURRENCY_NAMES.get(settings.way_currency, settings.way_currency))
        self.way_tier_var.set(TIER_LABELS.get(settings.way_tier, "一级"))
        self.way_interval_var.set(str(settings.way_interval_ms))
        self.map_interval_var.set(str(settings.map_interval_ms))
        self.set_cell_size(settings.cell_size)

    def sync_to(self, settings: Settings) -> None:
        """把控件值同步回配置（含校验夹取）。"""
        settings.combat_hotkey = self.combat_hotkey_var.get().strip() or settings.combat_hotkey
        settings.dump_hotkey = self.dump_hotkey_var.get().strip() or settings.dump_hotkey
        settings.way_hotkey = self.way_hotkey_var.get().strip() or settings.way_hotkey
        settings.map_hotkey = self.map_hotkey_var.get().strip() or settings.map_hotkey
        settings.rows = clamp(parse_int(self.rows_var.get(), settings.rows), 1, 30)
        settings.cols = clamp(parse_int(self.cols_var.get(), settings.cols), 1, 30)
        settings.dump_interval_ms = clamp(
            parse_int(self.dump_interval_var.get(), settings.dump_interval_ms),
            MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
        )
        for key, name in CURRENCY_NAMES.items():
            if name == self.way_currency_var.get():
                settings.way_currency = key
                break
        settings.way_tier = LABEL_TO_TIER.get(self.way_tier_var.get(), settings.way_tier)
        settings.way_interval_ms = clamp(
            parse_int(self.way_interval_var.get(), settings.way_interval_ms),
            MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
        )
        settings.map_interval_ms = clamp(
            parse_int(self.map_interval_var.get(), settings.map_interval_ms),
            MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
        )

    def set_cell_size(self, cell_size: int) -> None:
        """更新格子间距显示（未标定时提示）。"""
        self.cell_var.set(f"{cell_size} px" if cell_size > 0 else "未标定")
