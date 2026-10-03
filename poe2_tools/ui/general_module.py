#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通用模块：背包整理 / 石碑速点 / 地图速点（单页合并展示）。

背包网格（行/列/格子间距）为三个功能通用，只配置一份；各功能的独立参数
（热键 / 间隔 / 石碑货币与级别）分区平铺展示。顶部汇总行展示三个功能的当前热键。
热键行沿用最初版本样式：彩色标签展示当前热键 + 「设置热键」按钮进入按键捕获
（按任意键写入，Esc 取消），同时保留手动输入框可直接键入；两者都在「保存配置」后生效。
保存按钮统一经 on_save 回调走 app.save_config（校验夹取 + 写盘 + 重注册热键）。
"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import keyboard

from poe2_tools.bridge.bus import bus
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


class GeneralModule(ttk.Frame):
    """通用模块页：整理 / 石碑速点 / 地图速点合并单页。"""

    def __init__(
        self,
        master: tk.Misc,
        on_page_change: Callable[[str], None],
        on_save: Callable[[], None],
    ) -> None:
        super().__init__(master, padding=8)
        del on_page_change  # 单页无子页切换，保留参数与 app 调用签名兼容

        # 顶部汇总行：三个功能的当前热键
        self.summary_var = tk.StringVar()
        ttk.Label(self, textvariable=self.summary_var, foreground="#38bdf8",
                  font=("", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(
            self,
            text="背包网格为整理 / 石碑 / 地图通用；F3 标定左上角第一格，F4 标定右下角最后一格（自动推算格子间距）",
            foreground="#64748b",
        ).pack(anchor=tk.W, pady=(2, 0))

        # 控件变量
        self.rows_var = tk.StringVar()
        self.cols_var = tk.StringVar()
        self.cell_var = tk.StringVar(value="未标定")
        self.sort_hotkey_var = tk.StringVar()
        self.sort_interval_var = tk.StringVar()
        self.tablet_hotkey_var = tk.StringVar()
        self.currency_var = tk.StringVar()
        self.tier_var = tk.StringVar()
        self.tablet_interval_var = tk.StringVar()
        self.map_hotkey_var = tk.StringVar()
        self.map_interval_var = tk.StringVar()

        # 热键捕获状态（同时只允许一路捕获）与当前值展示标签
        self._capturing = False
        self._capture_buttons: list[ttk.Button] = []
        self._hotkey_displays: list[tuple[tk.StringVar, ttk.Label]] = []

        body = ttk.Frame(self)
        body.pack(anchor=tk.W, pady=(8, 0))

        # 背包（通用）
        bag = ttk.LabelFrame(body, text="背包（通用）", padding=6)
        bag.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        row = self._entry_row(bag, 0, "行数(1-30)", self.rows_var)
        row = self._entry_row(bag, row, "列数(1-30)", self.cols_var)
        ttk.Label(bag, text="格子间距").grid(row=row, column=0, sticky=tk.W, pady=2)
        ttk.Label(bag, textvariable=self.cell_var, foreground="#38bdf8").grid(
            row=row, column=1, sticky=tk.W, pady=2
        )

        # 背包整理
        sort = ttk.LabelFrame(body, text="背包整理", padding=6)
        sort.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        row = self._hotkey_row(sort, 0, "整理热键", "背包整理", self.sort_hotkey_var)
        self._entry_row(sort, row, "整理间隔(ms)", self.sort_interval_var)

        # 石碑速点
        tablet = ttk.LabelFrame(body, text="石碑速点（货币坐标在「研发 → 坐标」页标定，三级货币自动向右偏移）", padding=6)
        tablet.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        row = self._hotkey_row(tablet, 0, "石碑热键", "石碑速点", self.tablet_hotkey_var)
        ttk.Label(tablet, text="石碑货币").grid(row=row, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(
            tablet,
            textvariable=self.currency_var,
            values=[CURRENCY_NAMES[key] for key in CURRENCY_KEYS],
            state="readonly",
            width=10,
        ).grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1
        ttk.Label(tablet, text="石碑级别").grid(row=row, column=0, sticky=tk.W, pady=2)
        ttk.Combobox(
            tablet,
            textvariable=self.tier_var,
            values=list(LABEL_TO_TIER.keys()),
            state="readonly",
            width=10,
        ).grid(row=row, column=1, sticky=tk.W, pady=2)
        row += 1
        self._entry_row(tablet, row, "石碑间隔(ms)", self.tablet_interval_var)

        # 地图速点
        map_frame = ttk.LabelFrame(body, text="地图速点（固定流程：点金×1 → 崇高×4 → 瓦尔×1，完成后触发一次背包整理）", padding=6)
        map_frame.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        row = self._hotkey_row(map_frame, 0, "地图热键", "地图速点", self.map_hotkey_var)
        self._entry_row(map_frame, row, "地图间隔(ms)", self.map_interval_var)

        ttk.Button(self, text="保存配置", command=on_save).pack(anchor=tk.W, pady=(4, 0))

    @staticmethod
    def _entry_row(frame: ttk.Frame, row: int, label: str, var: tk.StringVar) -> int:
        """添加一行「标签 + 输入框」，返回下一行号。"""
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
        ttk.Entry(frame, textvariable=var, width=12).grid(row=row, column=1, sticky=tk.W, pady=2)
        return row + 1

    def _hotkey_row(
        self, frame: ttk.Frame, row: int, label: str, name: str, var: tk.StringVar
    ) -> int:
        """添加一行热键配置：当前值展示 + 按键捕获按钮 + 手动输入框，返回下一行号。"""
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky=tk.W, pady=2)
        display = ttk.Label(
            frame, foreground="#a855f7", font=("Consolas", 10, "bold"), width=8
        )
        display.grid(row=row, column=1, sticky=tk.W, padx=(4, 8), pady=2)
        button = ttk.Button(
            frame, text="设置热键", command=lambda: self._start_capture(name, var)
        )
        button.grid(row=row, column=2, sticky=tk.W, pady=2)
        ttk.Entry(frame, textvariable=var, width=10).grid(
            row=row, column=3, sticky=tk.W, padx=(8, 0), pady=2
        )
        self._capture_buttons.append(button)
        self._hotkey_displays.append((var, display))
        return row + 1

    # --------------------------------------------------------
    # 热键捕获（按任意键写入，Esc 取消；保存配置后生效）
    # --------------------------------------------------------
    def _refresh_hotkey_displays(self) -> None:
        """把各热键当前值刷新到彩色展示标签。"""
        for var, display in self._hotkey_displays:
            display.config(text=var.get().strip().upper() or "未设置")

    def _start_capture(self, name: str, var: tk.StringVar) -> None:
        """进入热键捕获模式：后台线程等待一次按键。"""
        if self._capturing:
            return
        self._capturing = True
        for button in self._capture_buttons:
            button.config(state=tk.DISABLED)
        bus.log(f"请按下新的「{name}」热键…（按 Esc 取消）")
        threading.Thread(target=self._capture_worker, args=(name, var), daemon=True).start()

    def _capture_worker(self, name: str, var: tk.StringVar) -> None:
        """后台线程：阻塞读取一次按键，结果转主线程处理。"""
        key = keyboard.read_key()
        self.after(0, lambda: self._finish_capture(name, var, key))

    def _finish_capture(self, name: str, var: tk.StringVar, key: str) -> None:
        """捕获结束（主线程）：恢复按钮，写入捕获结果。"""
        self._capturing = False
        for button in self._capture_buttons:
            button.config(state=tk.NORMAL)
        if key == "esc":
            bus.log("已取消热键捕获")
            return
        var.set(key)
        self._refresh_hotkey_displays()
        bus.log(f"「{name}」热键已捕获为 {key.upper()}，点「保存配置」后生效")

    @staticmethod
    def _read_hotkey(var: tk.StringVar, fallback: str) -> str:
        """读取热键输入（去空白转小写），为空时保留原值。"""
        hotkey = var.get().strip().lower()
        return hotkey or fallback

    # --------------------------------------------------------
    # 值同步
    # --------------------------------------------------------
    def load_from(self, settings: Settings) -> None:
        general = settings.general
        sort, tablet, map_click = general.sort, general.tablet, general.map_click

        self.rows_var.set(str(sort.rows))
        self.cols_var.set(str(sort.cols))
        self.set_cell_size(sort.cell_size)

        self.sort_hotkey_var.set(sort.hotkey)
        self.sort_interval_var.set(str(sort.interval_ms))

        self.tablet_hotkey_var.set(tablet.hotkey)
        self.currency_var.set(CURRENCY_NAMES.get(tablet.currency, tablet.currency))
        self.tier_var.set(TIER_LABELS.get(tablet.tier, "一级"))
        self.tablet_interval_var.set(str(tablet.interval_ms))

        self.map_hotkey_var.set(map_click.hotkey)
        self.map_interval_var.set(str(map_click.interval_ms))

        self.summary_var.set(
            f"背包整理 {sort.hotkey.upper()}    石碑 {tablet.hotkey.upper()}    地图 {map_click.hotkey.upper()}"
        )
        self._refresh_hotkey_displays()

    def sync_to(self, settings: Settings) -> None:
        general = settings.general
        sort, tablet, map_click = general.sort, general.tablet, general.map_click

        sort.rows = clamp(parse_int(self.rows_var.get(), sort.rows), 1, 30)
        sort.cols = clamp(parse_int(self.cols_var.get(), sort.cols), 1, 30)

        sort.hotkey = self._read_hotkey(self.sort_hotkey_var, sort.hotkey)
        sort.interval_ms = clamp(
            parse_int(self.sort_interval_var.get(), sort.interval_ms),
            MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
        )

        tablet.hotkey = self._read_hotkey(self.tablet_hotkey_var, tablet.hotkey)
        for key, name in CURRENCY_NAMES.items():
            if name == self.currency_var.get():
                tablet.currency = key
                break
        tablet.tier = LABEL_TO_TIER.get(self.tier_var.get(), tablet.tier)
        tablet.interval_ms = clamp(
            parse_int(self.tablet_interval_var.get(), tablet.interval_ms),
            MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
        )

        map_click.hotkey = self._read_hotkey(self.map_hotkey_var, map_click.hotkey)
        map_click.interval_ms = clamp(
            parse_int(self.map_interval_var.get(), map_click.interval_ms),
            MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
        )

    def set_cell_size(self, cell_size: int) -> None:
        """更新格子间距显示（F3/F4 标定结果，未标定时提示）。"""
        self.cell_var.set(f"{cell_size} px" if cell_size > 0 else "未标定")

    def select_page(self, _index: int) -> None:
        """单页无子页，保留方法与战斗模块调用签名兼容。"""

    def current_page(self) -> str:
        """合并单页固定返回 sort（背包网格所在配置，热键作用域不受子页影响）。"""
        return "sort"
