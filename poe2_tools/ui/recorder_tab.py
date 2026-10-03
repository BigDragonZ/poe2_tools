#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试页：F2 输入记录 + 释放频率分析。

实际采集逻辑在 modules/recorder/recorder.py，分析逻辑在 modules/recorder/analysis.py，
本页只负责状态展示与触发分析/清空。
"""

from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk

from poe2_tools.modules.recorder.analysis import load_rounds, render_report, summarize
from poe2_tools.modules.recorder.recorder import InputRecorder

HELP_TEXT = (
    "使用：停留在本页，切到游戏按 F2 开始记录，正常刷图；再按一次 F2 停止并保存一轮（logs/recordings/）。\n"
    "连续记录几轮后点「分析记录」提取技能释放频率；分析会自动过滤长按自动重复、"
    "抖动连点，并排除回城/喝水等停顿时间。\n"
    "注意：F2 只在本页生效，且本页内优先于战斗热键（不会误触战斗宏）；"
    "记录期间请勿启停刷图助手。"
)


class RecorderTab(ttk.Frame):
    """测试页（输入记录分析）。"""

    def __init__(self, master: tk.Misc, recorder: InputRecorder) -> None:
        super().__init__(master, padding=8)
        self.recorder = recorder

        frame = ttk.LabelFrame(self, text="输入记录（游戏中按 F2 开始/停止一轮）", padding=6)
        frame.pack(fill=tk.X)

        self._state_var = tk.StringVar(value="空闲")
        self._count_var = tk.StringVar(value="0")
        self._rounds_var = tk.StringVar(value="0")
        items = [
            ("状态", self._state_var, "#22c55e"),
            ("本轮事件", self._count_var, "#f59e0b"),
            ("已存轮数", self._rounds_var, "#38bdf8"),
        ]
        for col, (label, var, color) in enumerate(items):
            ttk.Label(frame, text=f"{label}:").grid(row=0, column=col * 2, sticky=tk.W)
            ttk.Label(frame, textvariable=var, foreground=color).grid(
                row=0, column=col * 2 + 1, sticky=tk.W, padx=(4, 16)
            )
        ttk.Button(frame, text="分析记录", width=10, command=self._analyze).grid(
            row=0, column=6, padx=(8, 6)
        )
        ttk.Button(frame, text="清空记录", width=10, command=self._clear).grid(row=0, column=7)

        self._report = tk.Text(
            self,
            height=14,
            font=("Consolas", 10),
            bg="#0f172a",
            fg="#e2e8f0",
            insertbackground="#e2e8f0",
        )
        self._report.pack(fill=tk.BOTH, expand=True, pady=(8, 0))
        self._report.insert(tk.END, "（尚无分析结果：先按 F2 记录几轮，再点「分析记录」）")
        self._report.config(state=tk.DISABLED)

        ttk.Label(self, text=HELP_TEXT, foreground="#64748b", justify=tk.LEFT).pack(
            anchor=tk.W, pady=(10, 0)
        )

    def set_status(self, status: dict) -> None:
        """刷新状态显示（主线程轮询调用）。"""
        self._state_var.set("记录中" if status.get("recording") else "空闲")
        self._count_var.set(str(status.get("event_count", 0)))
        self._rounds_var.set(str(status.get("rounds", 0)))

    def _analyze(self) -> None:
        """「分析记录」：读取全部轮次文件，渲染频率报告。"""
        reports = load_rounds(self.recorder.record_dir)
        if not reports:
            self._set_report("（没有记录文件：请先按 F2 记录至少一轮）")
            return
        self._set_report(render_report(summarize(reports)))

    def _clear(self) -> None:
        """「清空记录」：确认后删除全部轮次文件。"""
        rounds = len(self.recorder.list_rounds())
        if rounds == 0:
            return
        if not messagebox.askyesno("清空记录", f"确定删除全部 {rounds} 轮记录？"):
            return
        removed = self.recorder.clear_rounds()
        self._set_report(f"（已删除 {removed} 轮记录）")

    def _set_report(self, text: str) -> None:
        self._report.config(state=tk.NORMAL)
        self._report.delete("1.0", tk.END)
        self._report.insert(tk.END, text)
        self._report.config(state=tk.DISABLED)
