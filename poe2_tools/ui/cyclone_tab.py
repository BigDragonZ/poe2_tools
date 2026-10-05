#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风页：旋风引擎（CycloneEngine）控制。

- 运行状态区（运行/FSM 状态/Q 层数/E 充能/生命比值），由 app 轮询 engine.status() 推入
- Q/E 数字区标定为 F5 + 右键两角标记流程，ROI 写入 modules/cyclone/config.json
  （vision.q_roi/e_roi），实际逻辑在 app 控制器与 modules/cyclone/calibrate.py，
  本页只负责展示与回调
"""

from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import ttk
from typing import Any

from poe2_tools.config.settings import Settings

# 页脚说明文字
HELP_TEXT = (
    "使用流程：点「启动」（或游戏内按 F2）→ 引擎启动后按 F2/侧键 XButton2 切换 赶路/停止；\n"
    "赶路 = 按住左键（旋风斩移动+攻击）；Q 层数连续增长自动接敌放 E，Q 满 6 自动放 Q，\n"
    "E 充能回满（数字 3）自动放 E；光标附近出现物品黑框自动拾取；低血自动按 1 喝药；\n"
    "失焦自动停止，F12 急停释放全部按键。执行细节写入 logs/cyclone.log。"
)


class CycloneTab(ttk.Frame):
    """旋风页（旋风引擎控制）。"""

    def __init__(
        self,
        master: tk.Misc,
        on_calibrate: Callable[[str], None],
        on_engine_start: Callable[[], None],
        on_engine_stop: Callable[[], None],
    ) -> None:
        super().__init__(master, padding=8)

        engine = ttk.LabelFrame(self, text="旋风引擎（F2 启停 / 侧键 XButton2 切换赶路）", padding=6)
        engine.pack(fill=tk.X)

        ttk.Button(engine, text="启动", width=8, command=on_engine_start).grid(
            row=0, column=0, padx=(0, 6)
        )
        ttk.Button(engine, text="停止", width=8, command=on_engine_stop).grid(
            row=0, column=1, padx=(0, 12)
        )
        self._engine_run_var = tk.StringVar(value="未启动")
        self._engine_state_var = tk.StringVar(value="-")
        self._engine_q_var = tk.StringVar(value="-")
        self._engine_e_var = tk.StringVar(value="-")
        self._engine_life_var = tk.StringVar(value="-")
        status_items = [
            ("运行", self._engine_run_var, "#22c55e"),
            ("FSM 状态", self._engine_state_var, "#38bdf8"),
            ("Q 层数", self._engine_q_var, "#f59e0b"),
            ("E 充能", self._engine_e_var, "#f59e0b"),
            ("生命", self._engine_life_var, "#f472b6"),
        ]
        for col, (label, var, color) in enumerate(status_items):
            ttk.Label(engine, text=f"{label}:").grid(row=0, column=col * 2 + 2, sticky=tk.W)
            ttk.Label(engine, textvariable=var, foreground=color).grid(
                row=0, column=col * 2 + 3, sticky=tk.W, padx=(4, 12)
            )

        self._q_calib_button = ttk.Button(
            engine, text="标定 Q 数字区", width=14, command=lambda: on_calibrate("cyclone:q")
        )
        self._q_calib_button.grid(row=1, column=0, pady=(6, 0))
        ttk.Label(engine, text="Q 数字区:").grid(row=1, column=1, sticky=tk.W, pady=(6, 0))
        self._q_roi_var = tk.StringVar(value="未标定")
        ttk.Label(engine, textvariable=self._q_roi_var, foreground="#38bdf8").grid(
            row=1, column=2, columnspan=5, sticky=tk.W, padx=(4, 12), pady=(6, 0)
        )
        self._e_calib_button = ttk.Button(
            engine, text="标定 E 数字区", width=14, command=lambda: on_calibrate("cyclone:e")
        )
        self._e_calib_button.grid(row=2, column=0, pady=(4, 0))
        ttk.Label(engine, text="E 数字区:").grid(row=2, column=1, sticky=tk.W, pady=(4, 0))
        self._e_roi_var = tk.StringVar(value="未标定")
        ttk.Label(engine, textvariable=self._e_roi_var, foreground="#38bdf8").grid(
            row=2, column=2, columnspan=5, sticky=tk.W, padx=(4, 12), pady=(4, 0)
        )
        ttk.Label(
            engine,
            text="标定：点击按钮后切到游戏按 F5，右键点数字左上角，再右键点右下角",
            foreground="#64748b",
        ).grid(row=3, column=0, columnspan=8, sticky=tk.W, pady=(4, 0))

        ttk.Label(self, text=HELP_TEXT, foreground="#64748b", justify=tk.LEFT).pack(
            anchor=tk.W, pady=(10, 0)
        )

    # --------------------------------------------------------
    # 旋风引擎状态
    # --------------------------------------------------------
    def set_engine_status(self, status: dict) -> None:
        """刷新旋风引擎状态显示（主线程轮询调用，status 为 engine.status()）。"""
        running = bool(status.get("running"))
        self._engine_run_var.set("运行中" if running else "未启动")
        if not running:
            self._engine_state_var.set("-")
            self._engine_q_var.set("-")
            self._engine_e_var.set("-")
            self._engine_life_var.set("-")
            return
        state = str(status.get("state", "-"))
        if not status.get("digits_enabled"):
            state += "（数字检测禁用）"
        self._engine_state_var.set(state)
        q_stacks = status.get("q_stacks")
        self._engine_q_var.set(str(q_stacks) if q_stacks is not None else "-")
        e_charges = status.get("e_charges")
        self._engine_e_var.set(str(e_charges) if e_charges is not None else "-")
        life_ratio = status.get("life_ratio")
        self._engine_life_var.set(f"{life_ratio:.0%}" if life_ratio is not None else "-")

    def refresh_engine_roi(self, vision_cfg: dict[str, Any]) -> None:
        """刷新 Q/E 数字区 ROI 显示（vision_cfg 为 cyclone config.json 的 vision 段）。"""
        for key, var in (("q_roi", self._q_roi_var), ("e_roi", self._e_roi_var)):
            roi = vision_cfg.get(key)
            var.set(f"({roi[0]}, {roi[1]}) - ({roi[2]}, {roi[3]})" if roi else "未标定")

    def load_from(self, settings: Settings) -> None:
        """旋风页无 ini 配置可读（引擎参数在 modules/cyclone/config.json）。"""

    def sync_to(self, settings: Settings) -> None:
        """旋风页无可写配置（引擎参数在 modules/cyclone/config.json）。"""

    def set_pending(self, pending: str | None) -> None:
        """根据待标定目标更新按钮文案（等待 F5/标记时显示「取消」）。"""
        self._q_calib_button.config(text="取消" if pending == "cyclone:q" else "标定 Q 数字区")
        self._e_calib_button.config(text="取消" if pending == "cyclone:e" else "标定 E 数字区")
