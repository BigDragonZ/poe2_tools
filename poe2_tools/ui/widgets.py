#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
界面共享小部件与显示名映射。

KeyRowsFrame 复用于配置页与旋风页：每行一个按键，
包含策略下拉（禁用/连点/按住不放）、执行间隔输入框、随机抖动复选框。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from poe2_tools.config.settings import (
    MIN_INTERVAL_MS,
    MODE_DISABLED,
    MODE_HOLD,
    MODE_SPAM,
    KeyConfig,
)

# 策略内部值 <-> 界面显示名
MODE_LABELS = {MODE_DISABLED: "禁用", MODE_SPAM: "连点", MODE_HOLD: "按住不放"}
LABEL_TO_MODE = {label: mode for mode, label in MODE_LABELS.items()}
MODE_CHOICES = [MODE_LABELS[mode] for mode in (MODE_DISABLED, MODE_SPAM, MODE_HOLD)]

# 配置页按键显示名（内部标识沿用 AHK 命名）
SKILL_NAMES = {
    "LButton": "左键", "RButton": "右键", "Space": "空格",
    "q": "Q", "w": "W", "e": "E", "r": "R", "t": "T",
}
# 旋风页鼠标按键显示名
CYC_NAMES = {"LButton": "鼠标左键", "MButton": "鼠标中键", "RButton": "鼠标右键"}


def parse_int(text: str, default: int) -> int:
    """解析整数输入，非法时回退默认值。"""
    try:
        return int(text.strip())
    except (TypeError, ValueError):
        return default


def clamp(value: int, lo: int, hi: int) -> int:
    """把整数夹取到 [lo, hi] 区间。"""
    return max(lo, min(hi, value))


class KeyRowsFrame(ttk.Frame):
    """一组按键配置行：策略下拉 + 执行间隔输入 + 抖动毫秒输入。"""

    def __init__(self, master: tk.Misc, keys: list[str], names: dict[str, str]) -> None:
        super().__init__(master, padding=4)
        self._keys = list(keys)
        self._mode_vars: dict[str, tk.StringVar] = {}
        self._interval_vars: dict[str, tk.StringVar] = {}
        self._jitter_vars: dict[str, tk.StringVar] = {}

        for col, title in enumerate(("按键", "策略", "执行间隔(ms)", "随机抖动(+ms)")):
            ttk.Label(self, text=title, foreground="#64748b").grid(
                row=0, column=col, sticky=tk.W, padx=(0, 8), pady=(0, 4)
            )

        for row, key in enumerate(self._keys, start=1):
            ttk.Label(self, text=names.get(key, key), width=10).grid(
                row=row, column=0, sticky=tk.W, padx=(0, 8), pady=2
            )
            mode_var = tk.StringVar(value=MODE_LABELS[MODE_DISABLED])
            ttk.Combobox(
                self, textvariable=mode_var, values=MODE_CHOICES,
                state="readonly", width=8,
            ).grid(row=row, column=1, sticky=tk.W, padx=(0, 8), pady=2)
            interval_var = tk.StringVar(value="300")
            ttk.Entry(self, textvariable=interval_var, width=8).grid(
                row=row, column=2, sticky=tk.W, padx=(0, 8), pady=2
            )
            jitter_var = tk.StringVar(value="0")
            ttk.Entry(self, textvariable=jitter_var, width=8).grid(
                row=row, column=3, sticky=tk.W, pady=2
            )
            self._mode_vars[key] = mode_var
            self._interval_vars[key] = interval_var
            self._jitter_vars[key] = jitter_var

    def load_from(self, configs: dict[str, KeyConfig]) -> None:
        """把配置写入控件。"""
        for key in self._keys:
            config = configs.get(key)
            if config is None:
                continue
            self._mode_vars[key].set(MODE_LABELS.get(config.mode, MODE_LABELS[MODE_DISABLED]))
            self._interval_vars[key].set(str(config.interval_ms))
            self._jitter_vars[key].set(str(config.jitter_ms))

    def sync_to(self, configs: dict[str, KeyConfig]) -> None:
        """把控件值同步回配置（间隔夹取到 ≥ MIN_INTERVAL_MS，抖动夹取到 0-5000）。"""
        for key in self._keys:
            config = configs.setdefault(key, KeyConfig())
            config.mode = LABEL_TO_MODE.get(self._mode_vars[key].get(), MODE_DISABLED)
            interval = parse_int(self._interval_vars[key].get(), config.interval_ms)
            config.interval_ms = max(MIN_INTERVAL_MS, interval)
            config.jitter_ms = clamp(parse_int(self._jitter_vars[key].get(), config.jitter_ms), 0, 5000)
