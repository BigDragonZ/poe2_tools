#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
战斗模块：配置页 + 旋风页（内嵌 Notebook）+ 战斗设置区。

- 内嵌标签页：配置1（ProfileTab，8 键策略）、旋风（CycloneTab，鼠标三键 + 刷图自动化控制）
- 战斗设置区：战斗宏热键 + 保存按钮
- 子页切换经 on_page_change 上报 app（page_id ∈ {"profile", "cyclone"}），
  用于热键作用域与 active_profile 跟随
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from poe2_tools.config.settings import Settings
from poe2_tools.ui.cyclone_tab import CycloneTab
from poe2_tools.ui.profile_tab import ProfileTab

# 内嵌子页顺序与 page_id（索引 0=配置1，1=旋风）
PAGE_IDS = ("profile", "cyclone")


class CombatModule(ttk.Frame):
    """战斗模块页。"""

    def __init__(
        self,
        master: tk.Misc,
        on_page_change: Callable[[str], None],
        on_save: Callable[[], None],
        on_calibrate: Callable[[str], None],
        on_mapping_start: Callable[[], None],
        on_mapping_stop: Callable[[], None],
    ) -> None:
        super().__init__(master)
        self._on_page_change = on_page_change

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.profile_tab = ProfileTab(self.notebook, 1)
        self.notebook.add(self.profile_tab, text="配置1")
        self.cyclone_tab = CycloneTab(
            self.notebook,
            on_calibrate=on_calibrate,
            on_mapping_start=on_mapping_start,
            on_mapping_stop=on_mapping_stop,
        )
        self.notebook.add(self.cyclone_tab, text="旋风")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        settings_frame = ttk.LabelFrame(self, text="战斗设置", padding=6)
        settings_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(settings_frame, text="战斗宏热键").grid(row=0, column=0, sticky=tk.W, pady=2)
        self.hotkey_var = tk.StringVar()
        ttk.Entry(settings_frame, textvariable=self.hotkey_var, width=12).grid(
            row=0, column=1, sticky=tk.W, padx=(4, 12), pady=2
        )
        ttk.Button(settings_frame, text="保存配置", command=on_save).grid(
            row=0, column=2, sticky=tk.W, pady=2
        )

    # --------------------------------------------------------
    # 值同步
    # --------------------------------------------------------
    def load_from(self, settings: Settings) -> None:
        """把配置写入控件。"""
        self.profile_tab.load_from(settings.combat.profiles[0])
        self.cyclone_tab.load_from(settings)
        self.hotkey_var.set(settings.combat.hotkey)

    def sync_to(self, settings: Settings) -> None:
        """把控件值同步回配置（热键非空，去空白转小写）。"""
        self.profile_tab.sync_to(settings.combat.profiles[0])
        self.cyclone_tab.sync_to(settings)
        hotkey = self.hotkey_var.get().strip().lower()
        if hotkey:
            settings.combat.hotkey = hotkey

    # --------------------------------------------------------
    # 透传（旋风页 / 刷图自动化）
    # --------------------------------------------------------
    def set_pending(self, pending: str | None) -> None:
        """透传待标定状态给旋风页（按钮文案）。"""
        self.cyclone_tab.set_pending(pending)

    def refresh_mapping_roi(self, settings: Settings) -> None:
        self.cyclone_tab.refresh_mapping_roi(settings)

    def set_mapping_status(self, status: dict) -> None:
        self.cyclone_tab.set_mapping_status(status)

    def select_page(self, index: int) -> None:
        """按索引选中内嵌子页（0=配置1，1=旋风）。"""
        if 0 <= index < len(PAGE_IDS):
            self.notebook.select(index)

    def current_page(self) -> str:
        """当前内嵌子页 page_id。"""
        return PAGE_IDS[self.notebook.index(self.notebook.select())]

    # --------------------------------------------------------
    # 内部
    # --------------------------------------------------------
    def _on_tab_changed(self, _event: tk.Event) -> None:
        self._on_page_change(self.current_page())
