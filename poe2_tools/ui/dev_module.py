#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
研发模块：开发（测量）/ 测试（输入记录）/ 坐标（货币标定）+ 研发设置区。

- 内嵌标签页：开发（DevTab）、测试（RecorderTab）、坐标（CoordsTab）
- 研发设置区：调试模式 + 日志级别 + 保存按钮（settings.dev.*）
- 子页切换经 on_page_change 上报 app（page_id ∈ {"dev", "test", "coords"}）
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from poe2_tools.config.settings import LOG_LEVELS, Settings
from poe2_tools.modules.recorder.recorder import InputRecorder
from poe2_tools.ui.coords_tab import CoordsTab
from poe2_tools.ui.dev_tab import DevTab
from poe2_tools.ui.recorder_tab import RecorderTab

# 内嵌子页顺序与 page_id
PAGE_IDS = ("dev", "test", "coords")


class DevModule(ttk.Frame):
    """研发模块页。"""

    def __init__(
        self,
        master: tk.Misc,
        on_page_change: Callable[[str], None],
        on_save: Callable[[], None],
        on_calibrate: Callable[[str], None],
        recorder: InputRecorder,
    ) -> None:
        super().__init__(master)
        self._on_page_change = on_page_change

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill=tk.BOTH, expand=True)

        self.dev_tab = DevTab(self.notebook, on_calibrate=on_calibrate)
        self.notebook.add(self.dev_tab, text="开发")
        self.recorder_tab = RecorderTab(self.notebook, recorder)
        self.notebook.add(self.recorder_tab, text="测试")
        self.coords_tab = CoordsTab(self.notebook, on_calibrate=on_calibrate)
        self.notebook.add(self.coords_tab, text="坐标")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        settings_frame = ttk.LabelFrame(self, text="研发设置", padding=6)
        settings_frame.pack(fill=tk.X, pady=(8, 0))
        self.debug_var = tk.BooleanVar()
        ttk.Checkbutton(settings_frame, text="调试模式", variable=self.debug_var).grid(
            row=0, column=0, sticky=tk.W, pady=2
        )
        ttk.Label(settings_frame, text="日志级别").grid(
            row=0, column=1, sticky=tk.W, padx=(16, 0), pady=2
        )
        self.log_level_var = tk.StringVar()
        ttk.Combobox(
            settings_frame,
            textvariable=self.log_level_var,
            values=list(LOG_LEVELS),
            state="readonly",
            width=8,
        ).grid(row=0, column=2, sticky=tk.W, padx=(4, 12), pady=2)
        ttk.Button(settings_frame, text="保存配置", command=on_save).grid(
            row=0, column=3, sticky=tk.W, pady=2
        )

    # --------------------------------------------------------
    # 值同步
    # --------------------------------------------------------
    def load_from(self, settings: Settings) -> None:
        """把配置写入控件，并刷新各子页显示。"""
        self.debug_var.set(settings.dev.debug)
        self.log_level_var.set(settings.dev.log_level)
        self.dev_tab.refresh(settings)
        self.coords_tab.refresh_coords(settings)

    def sync_to(self, settings: Settings) -> None:
        """把控件值同步回配置。"""
        settings.dev.debug = bool(self.debug_var.get())
        level = self.log_level_var.get().strip().upper()
        if level in LOG_LEVELS:
            settings.dev.log_level = level

    # --------------------------------------------------------
    # 透传（子页）
    # --------------------------------------------------------
    def set_pending(self, pending: str | None) -> None:
        """透传待标定状态给开发/坐标页（按钮文案）。"""
        self.dev_tab.set_pending(pending)
        self.coords_tab.set_pending(pending)

    def refresh(self, settings: Settings) -> None:
        """透传开发页测量结果刷新。"""
        self.dev_tab.refresh(settings)

    def refresh_coords(self, settings: Settings) -> None:
        """透传坐标页货币坐标刷新。"""
        self.coords_tab.refresh_coords(settings)

    def set_status(self, status: dict) -> None:
        """透传测试页输入记录状态刷新。"""
        self.recorder_tab.set_status(status)

    def select_page(self, index: int) -> None:
        if 0 <= index < len(PAGE_IDS):
            self.notebook.select(index)

    def current_page(self) -> str:
        return PAGE_IDS[self.notebook.index(self.notebook.select())]

    # --------------------------------------------------------
    # 内部
    # --------------------------------------------------------
    def _on_tab_changed(self, _event: tk.Event) -> None:
        self._on_page_change(self.current_page())
