#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""背包整理页：热键设置、网格设置与标定说明。"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import keyboard

from poe2_tools import bag


class BagTab(ttk.Frame):
    """背包整理模块界面。"""

    def __init__(
        self,
        master: tk.Misc,
        log: Callable[[str], None],
        on_hotkey_changed: Callable[[], None],
    ) -> None:
        super().__init__(master, padding=12)
        self.log = log
        self.on_hotkey_changed = on_hotkey_changed
        self.capturing = False

        # ---------- 热键设置 ----------
        hotkey_frame = ttk.LabelFrame(self, text="热键设置", padding=8)
        hotkey_frame.pack(fill=tk.X)

        self.dump_hotkey_var = tk.StringVar(value=bag.get_dump_hotkey())
        ttk.Label(hotkey_frame, text="整理热键：").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(
            hotkey_frame,
            textvariable=self.dump_hotkey_var,
            foreground="#a855f7",
            font=("Consolas", 10, "bold"),
        ).grid(row=0, column=1, sticky=tk.W, padx=(4, 8))
        self.btn_capture = ttk.Button(hotkey_frame, text="设置热键", command=self.capture_hotkey)
        self.btn_capture.grid(row=0, column=2, sticky=tk.W)

        # ---------- 背包设置 ----------
        grid_frame = ttk.LabelFrame(self, text="背包设置", padding=8)
        grid_frame.pack(fill=tk.X, pady=(8, 0))

        rows, cols = bag.get_grid_size()
        self.rows_var = tk.StringVar(value=str(rows))
        self.cols_var = tk.StringVar(value=str(cols))

        ttk.Label(grid_frame, text="行数：").grid(row=0, column=0, sticky=tk.W)
        ttk.Spinbox(grid_frame, from_=1, to=30, increment=1, textvariable=self.rows_var, width=6).grid(
            row=0, column=1, sticky=tk.W, padx=(4, 16)
        )
        ttk.Label(grid_frame, text="列数：").grid(row=0, column=2, sticky=tk.W)
        ttk.Spinbox(grid_frame, from_=1, to=30, increment=1, textvariable=self.cols_var, width=6).grid(
            row=0, column=3, sticky=tk.W, padx=(4, 16)
        )
        ttk.Button(grid_frame, text="保存背包设置", command=self.save_grid).grid(row=0, column=4, sticky=tk.W)

        # ---------- 标定说明 ----------
        cal_frame = ttk.LabelFrame(self, text="标定", padding=8)
        cal_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(
            cal_frame,
            text="在 POE2 背包界面：鼠标移到某格中心按 F3，移到同一行右侧相邻格中心按 F4，间距自动保存。",
            wraplength=460,
            justify=tk.LEFT,
        ).pack(anchor=tk.W)

    # ============================================================
    # 热键捕获
    # ============================================================
    def capture_hotkey(self) -> None:
        """进入热键捕获模式：按下任意键作为新整理热键，Esc 取消。"""
        if self.capturing:
            return
        self.capturing = True
        self.btn_capture.config(state=tk.DISABLED)
        self.log("请按下新的整理热键…（按 Esc 取消）")
        threading.Thread(target=self._capture_worker, daemon=True).start()

    def _capture_worker(self) -> None:
        """在后台线程等待按键并保存。"""
        key = keyboard.read_key()
        if key == "esc":
            self.log("已取消热键设置。")
        else:
            bag.set_dump_hotkey(key)
            self.log(f"整理热键已设置为: {key}")
            self.after(0, self.on_hotkey_changed)
            self.after(0, lambda: self.dump_hotkey_var.set(key))

        def restore() -> None:
            self.capturing = False
            self.btn_capture.config(state=tk.NORMAL)

        self.after(0, restore)

    # ============================================================
    # 背包设置保存
    # ============================================================
    def save_grid(self) -> None:
        """把行列数配置写入 poe2_tools.ini。"""
        try:
            rows = int(self.rows_var.get())
            cols = int(self.cols_var.get())
        except ValueError:
            rows, cols = bag.DEFAULT_ROWS, bag.DEFAULT_COLS
        rows = max(rows, 1)
        cols = max(cols, 1)
        self.rows_var.set(str(rows))
        self.cols_var.set(str(cols))

        bag.set_grid_size(rows, cols)
        self.log(f"背包设置已保存: {rows} 行 × {cols} 列")
