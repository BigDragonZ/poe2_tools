#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风配置页：鼠标三键策略 + 刷图自动化控制分区。

刷图 Q=6 标定为 F5 + 右键两角标记流程，实际逻辑在 app 控制器与
modules/mapping/calibrate.py，本页只负责展示与回调。
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

from poe2_tools.config.settings import CYC_KEYS, Settings
from poe2_tools.ui.widgets import CYC_NAMES, KeyRowsFrame

# 页脚说明文字
HELP_TEXT = (
    "Q=6 标定：点击「标定 Q=6」后切到游戏按 F5 进入标记，"
    "右键点击检测数字的左上角，再右键点击右下角，自动记录区域并截取模板（templates/q6.png）。\n"
    "点「启动」后切回游戏窗口，检测到 POE2 前台自动启动（15 秒内有效）；"
    "启动刷图后会对标记区域截图做匹配测试，结果写入 logs/mapping.log。"
)


class CycloneTab(ttk.Frame):
    """旋风配置页（含刷图自动化控制分区）。"""

    def __init__(
        self,
        master: tk.Misc,
        on_calibrate: Callable[[str], None],
        on_mapping_start: Callable[[], None],
        on_mapping_stop: Callable[[], None],
    ) -> None:
        super().__init__(master, padding=8)
        ttk.Label(
            self,
            text="旋风配置：鼠标按键策略",
            foreground="#64748b",
        ).pack(anchor=tk.W)
        self.rows = KeyRowsFrame(self, CYC_KEYS, CYC_NAMES)
        self.rows.pack(anchor=tk.W, pady=(6, 0))

        mapping = ttk.LabelFrame(self, text="刷图自动化（侧键 XButton2 切换 移动/关闭）", padding=6)
        mapping.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(mapping, text="启动", width=8, command=on_mapping_start).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(mapping, text="停止", width=8, command=on_mapping_stop).grid(
            row=0, column=1, padx=(0, 12)
        )
        self._mapping_run_var = tk.StringVar(value="未启动")
        self._mapping_state_var = tk.StringVar(value="-")
        self._mapping_q_var = tk.StringVar(value="-")
        status_items = [
            ("运行", self._mapping_run_var, "#22c55e"),
            ("FSM 状态", self._mapping_state_var, "#38bdf8"),
            ("Q 检测", self._mapping_q_var, "#f59e0b"),
        ]
        for col, (label, var, color) in enumerate(status_items):
            ttk.Label(mapping, text=f"{label}:").grid(row=0, column=col * 2 + 2, sticky=tk.W)
            ttk.Label(mapping, textvariable=var, foreground=color).grid(
                row=0, column=col * 2 + 3, sticky=tk.W, padx=(4, 12)
            )
        self._q6_calib_button = ttk.Button(
            mapping, text="标定 Q=6", width=10, command=lambda: on_calibrate("mapping:q6")
        )
        self._q6_calib_button.grid(row=1, column=0, pady=(6, 0))
        ttk.Label(mapping, text="Q6 区域:").grid(row=1, column=1, sticky=tk.W, pady=(6, 0))
        self._mapping_roi_var = tk.StringVar(value="未标定")
        ttk.Label(mapping, textvariable=self._mapping_roi_var, foreground="#38bdf8").grid(
            row=1, column=2, columnspan=5, sticky=tk.W, padx=(4, 12), pady=(6, 0)
        )
        ttk.Label(
            mapping,
            text="标定：点击按钮后切到游戏按 F5，右键点数字左上角，再右键点右下角",
            foreground="#64748b",
        ).grid(row=2, column=0, columnspan=8, sticky=tk.W, pady=(4, 0))

        ttk.Label(self, text=HELP_TEXT, foreground="#64748b", justify=tk.LEFT).pack(
            anchor=tk.W, pady=(10, 0)
        )

    def set_mapping_status(self, status: dict) -> None:
        """刷新刷图自动化状态显示（主线程轮询调用）。"""
        running = bool(status.get("running"))
        state = str(status.get("state", "-"))
        ui_open = bool(status.get("ui_open"))
        self._mapping_run_var.set("运行中" if running else "未启动")
        self._mapping_state_var.set(f"{state}（UI 挂起）" if ui_open else state)
        if not running:
            self._mapping_q_var.set("-")
        else:
            self._mapping_q_var.set("启用" if status.get("q_enabled") else "禁用")

    def load_from(self, settings: Settings) -> None:
        """载入鼠标键配置与 Q6 区域显示。"""
        self.rows.load_from(settings.combat.cyclone)
        self.refresh_mapping_roi(settings)

    def sync_to(self, settings: Settings) -> None:
        """把控件值同步回旋风配置。"""
        self.rows.sync_to(settings.combat.cyclone)

    def refresh_mapping_roi(self, settings: Settings) -> None:
        """刷新 Q6 检测区域显示。"""
        roi = settings.combat.q6_roi
        self._mapping_roi_var.set(
            f"({roi[0]}, {roi[1]}) - ({roi[2]}, {roi[3]})" if roi is not None else "未标定"
        )

    def set_pending(self, pending: str | None) -> None:
        """根据待标定目标更新按钮文案（等待 F5/标记时显示「取消」）。"""
        self._q6_calib_button.config(text="取消" if pending == "mapping:q6" else "标定 Q=6")
