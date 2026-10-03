#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
日志面板：可折叠 + 级别着色 + 级别过滤。

内部保留 (level, text) 记录列表（上限 MAX_RECORDS 防膨胀），
set_filter 变更时整体重渲染；append 线程安全（任意线程经 root.after 转主线程）。
"""

from __future__ import annotations

import time
import tkinter as tk
from tkinter import scrolledtext, ttk

# 级别 → 前景色
LEVEL_COLORS = {
    "DEBUG": "#64748b",
    "INFO": "#e2e8f0",
    "WARN": "#f59e0b",
    "ERROR": "#ef4444",
}

# 级别权重（越大越严重）
_LEVEL_ORDER = {"DEBUG": 0, "INFO": 1, "WARN": 2, "ERROR": 3}

# 保留的日志记录上限（超出丢弃最旧）
MAX_RECORDS = 2000


class LogPanel(ttk.Frame):
    """底部日志面板（标题行 + 可折叠日志正文）。"""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self._expanded = True
        self._min_level = "INFO"
        self._debug = False
        self._records: list[tuple[str, str]] = []

        header = ttk.Frame(self)
        header.pack(fill=tk.X)
        ttk.Label(header, text="日志", font=("", 10, "bold")).pack(side=tk.LEFT)
        self._toggle_button = ttk.Button(header, text="折叠 ▲", width=8, command=self.toggle)
        self._toggle_button.pack(side=tk.RIGHT)

        self._body = ttk.Frame(self)
        self._body.pack(fill=tk.BOTH, expand=True)
        self.text = scrolledtext.ScrolledText(
            self._body,
            wrap=tk.WORD,
            height=8,
            font=("Consolas", 10),
            bg="#0f172a",
            fg="#e2e8f0",
            insertbackground="#e2e8f0",
        )
        self.text.pack(fill=tk.BOTH, expand=True)
        for level, color in LEVEL_COLORS.items():
            self.text.tag_configure(level, foreground=color)

    # --------------------------------------------------------
    # 折叠 / 展开
    # --------------------------------------------------------
    def toggle(self) -> None:
        """切换折叠状态：折叠时只留标题行。"""
        if self._expanded:
            self._body.pack_forget()
            self._toggle_button.config(text="展开 ▼")
        else:
            self._body.pack(fill=tk.BOTH, expand=True)
            self._toggle_button.config(text="折叠 ▲")
        self._expanded = not self._expanded

    # --------------------------------------------------------
    # 追加与过滤
    # --------------------------------------------------------
    def append(self, message: str, level: str = "INFO") -> None:
        """追加一条日志（线程安全）。"""
        level = level if level in LEVEL_COLORS else "INFO"
        full = f"[{time.strftime('%H:%M:%S')}] {message}"

        def _do() -> None:
            self._records.append((level, full))
            if len(self._records) > MAX_RECORDS:
                del self._records[: len(self._records) - MAX_RECORDS]
            if self._visible(level):
                self._insert(level, full)

        try:
            self.after(0, _do)
        except RuntimeError:
            pass  # 窗口已销毁

    def set_filter(self, min_level: str, debug: bool) -> None:
        """设置过滤条件并重渲染：DEBUG 级仅当 debug=True 或 min_level=DEBUG 时显示。"""
        self._min_level = min_level if min_level in _LEVEL_ORDER else "INFO"
        self._debug = debug
        self.text.config(state=tk.NORMAL)
        self.text.delete("1.0", tk.END)
        for level, full in self._records:
            if self._visible(level):
                self._insert(level, full)

    # --------------------------------------------------------
    # 内部
    # --------------------------------------------------------
    def _visible(self, level: str) -> bool:
        """判断某级别在当前过滤条件下是否显示。"""
        if level == "DEBUG" and not (self._debug or self._min_level == "DEBUG"):
            return False
        return _LEVEL_ORDER[level] >= _LEVEL_ORDER[self._min_level]

    def _insert(self, level: str, full: str) -> None:
        self.text.insert(tk.END, full + "\n", level)
        self.text.see(tk.END)
