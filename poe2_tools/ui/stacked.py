#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
堆叠视图容器：等价 Qt 的 QStackedWidget。

所有子页用 place 铺满容器，show() 通过 tkraise 置顶切换；
供主窗口在「战斗 / 通用 / 研发 / 交易」四个模块间切换。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class StackedView(ttk.Frame):
    """堆叠页面容器。"""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master)
        self._pages: dict[str, ttk.Frame] = {}
        self._current: str | None = None

    def add(self, name: str, frame: ttk.Frame) -> None:
        """登记一个页面：铺满容器，初始隐藏于最底层。"""
        self._pages[name] = frame
        frame.place(in_=self, x=0, y=0, relwidth=1, relheight=1)

    def show(self, name: str) -> None:
        """切换到指定页面。"""
        frame = self._pages[name]
        frame.tkraise()
        self._current = name

    @property
    def current(self) -> str | None:
        """当前页面名（未切换过则为 None）。"""
        return self._current
