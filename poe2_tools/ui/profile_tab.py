#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战斗配置页：8 个按键的策略 / 执行间隔 / 随机抖动。"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from poe2_tools.config.settings import SKILL_KEYS, KeyConfig
from poe2_tools.ui.widgets import SKILL_NAMES, KeyRowsFrame


class ProfileTab(ttk.Frame):
    """单个战斗配置页。"""

    def __init__(self, master: tk.Misc, index: int) -> None:
        super().__init__(master, padding=8)
        ttk.Label(
            self,
            text=f"配置{index}：为每个按键选择触发策略，战斗宏热键在游戏中启停",
            foreground="#64748b",
        ).pack(anchor=tk.W)
        self.rows = KeyRowsFrame(self, SKILL_KEYS, SKILL_NAMES)
        self.rows.pack(anchor=tk.W, pady=(6, 0))

    def load_from(self, configs: dict[str, KeyConfig]) -> None:
        self.rows.load_from(configs)

    def sync_to(self, configs: dict[str, KeyConfig]) -> None:
        self.rows.sync_to(configs)
