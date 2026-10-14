#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地图模块：地图速点独立配置页。

固定流程：点金×1 → 崇高×2 → 瓦尔×1（点金固定出 4 词，崇高 2 颗补满 6 词），
完成后触发一次背包整理；货币坐标在「研发 → 坐标」页标定；
背包网格（行/列/格子间距）在「通用」页配置。
热键行样式：彩色标签展示当前热键 + 「设置热键」按钮进入按键捕获
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
    MAX_BATCH_INTERVAL_MS,
    MIN_BATCH_INTERVAL_MS,
    Settings,
)
from poe2_tools.ui.widgets import clamp, parse_int


class MapModule(ttk.Frame):
    """地图模块页：地图速点配置。"""

    def __init__(
        self,
        master: tk.Misc,
        on_page_change: Callable[[str], None],
        on_save: Callable[[], None],
    ) -> None:
        super().__init__(master, padding=8)
        del on_page_change  # 单页无子页切换，保留参数与 app 调用签名兼容

        # 顶部汇总行：当前热键
        self.summary_var = tk.StringVar()
        ttk.Label(self, textvariable=self.summary_var, foreground="#38bdf8",
                  font=("", 10, "bold")).pack(anchor=tk.W)
        ttk.Label(
            self,
            text="背包网格（行/列/格子间距）在「通用」页配置，与整理/石碑通用",
            foreground="#64748b",
        ).pack(anchor=tk.W, pady=(2, 0))

        # 控件变量
        self.map_hotkey_var = tk.StringVar()
        self.map_interval_var = tk.StringVar()
        self.vaal_hotkey_var = tk.StringVar()
        self.vaal_interval_var = tk.StringVar()
        self.vaal_tier_var = tk.StringVar()
        self.vaal_threshold_var = tk.StringVar()

        # 热键捕获状态（同时只允许一路捕获）与当前值展示标签
        self._capturing = False
        self._capture_buttons: list[ttk.Button] = []
        self._hotkey_displays: list[tuple[tk.StringVar, ttk.Label]] = []

        body = ttk.Frame(self)
        body.pack(anchor=tk.W, pady=(8, 0))

        # 地图速点
        map_frame = ttk.LabelFrame(body, text="地图速点（固定流程：点金×1 → 崇高×2 → 瓦尔×1，完成后触发一次背包整理）", padding=6)
        map_frame.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        row = self._hotkey_row(map_frame, 0, "地图热键", "地图速点", self.map_hotkey_var)
        self._entry_row(map_frame, row, "地图间隔(ms)", self.map_interval_var)

        # 瓦地图（仓库批量）
        vaal_frame = ttk.LabelFrame(
            body,
            text="瓦地图（打开仓库后按热键：取未满 6 词未污染图 → 点金/崇高补满 → 瓦前检查 → 瓦尔 → 按 T16/数值/8词分流存回）",
            padding=6,
        )
        vaal_frame.pack(anchor=tk.W, fill=tk.X, pady=(0, 6))
        row = self._hotkey_row(vaal_frame, 0, "瓦图热键", "瓦地图", self.vaal_hotkey_var)
        row = self._entry_row(vaal_frame, row, "瓦图间隔(ms)", self.vaal_interval_var)
        row = self._entry_row(vaal_frame, row, "地图阶级(1-16)", self.vaal_tier_var)
        self._entry_row(vaal_frame, row, "100仓阈值(稀有度+效能)", self.vaal_threshold_var)

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
        map_click = settings.general.map_click
        map_vaal = settings.general.map_vaal

        self.map_hotkey_var.set(map_click.hotkey)
        self.map_interval_var.set(str(map_click.interval_ms))
        self.vaal_hotkey_var.set(map_vaal.hotkey)
        self.vaal_interval_var.set(str(map_vaal.interval_ms))
        self.vaal_tier_var.set(str(map_vaal.tier))
        self.vaal_threshold_var.set(str(map_vaal.value_threshold))

        self.summary_var.set(f"地图速点 {map_click.hotkey.upper()}｜瓦地图 {map_vaal.hotkey.upper()}")
        self._refresh_hotkey_displays()

    def sync_to(self, settings: Settings) -> None:
        map_click = settings.general.map_click
        map_vaal = settings.general.map_vaal

        map_click.hotkey = self._read_hotkey(self.map_hotkey_var, map_click.hotkey)
        map_click.interval_ms = clamp(
            parse_int(self.map_interval_var.get(), map_click.interval_ms),
            MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
        )
        map_vaal.hotkey = self._read_hotkey(self.vaal_hotkey_var, map_vaal.hotkey)
        map_vaal.interval_ms = clamp(
            parse_int(self.vaal_interval_var.get(), map_vaal.interval_ms),
            MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
        )
        map_vaal.tier = clamp(parse_int(self.vaal_tier_var.get(), map_vaal.tier), 1, 16)
        map_vaal.value_threshold = clamp(
            parse_int(self.vaal_threshold_var.get(), map_vaal.value_threshold), 0, 1000
        )

    def select_page(self, _index: int) -> None:
        """单页无子页，保留方法与战斗模块调用签名兼容。"""

    def current_page(self) -> str:
        """单页固定返回 map（热键作用域不受子页影响）。"""
        return "map"
