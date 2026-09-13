#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口：运行状态区 + 四模块标签页 + 日志区，负责全局热键注册。

- 整理热键（默认 F1，可在背包整理页修改）：一键存仓
- F3 / F4：标定背包同一行相邻两格中心
- F12：紧急停止所有任务并释放按键
"""

from __future__ import annotations

import platform
import sys
import threading
import time

# ============================================================
# 平台检查
# ============================================================
if platform.system() != "Windows":
    print("本工具仅能在 Windows 原生环境下运行。")
    sys.exit(1)

import keyboard
import tkinter as tk
from tkinter import scrolledtext, ttk

from poe2_tools import bag, common
from poe2_tools.ui.bag_tab import BagTab
from poe2_tools.ui.combat_tab import CombatTab
from poe2_tools.ui.placeholder_tab import PlaceholderTab

# 紧急停止热键（固定，不可修改，确保任何场景都能中断）
STOP_HOTKEY = "f12"

# 标定热键（固定）
CALIBRATE_KEY_FIRST = "f3"
CALIBRATE_KEY_SECOND = "f4"


class Poe2ToolsApp:
    """Tkinter 主界面。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("POE2 游玩工具")
        self.root.geometry("560x620")
        self.root.minsize(520, 560)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self.hotkey_handlers: dict[str, object] = {}

        self._build_status()
        self._build_tabs()
        self._build_log()

        self.register_hotkeys()
        self.log(
            f"控制台已启动。整理热键: {bag.get_dump_hotkey()}，"
            f"标定: F3/F4，停止: {STOP_HOTKEY}"
        )
        self.update_status()

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_status(self) -> None:
        """运行状态区：POE2 前台 / 背包标定 / 整理状态。"""
        status_frame = ttk.LabelFrame(self.root, text="运行状态", padding=8)
        status_frame.pack(fill=tk.X, padx=12, pady=(8, 0))

        self.poe_var = tk.StringVar(value="检测中…")
        self.cal_var = tk.StringVar(value="检测中…")
        self.dump_var = tk.StringVar(value="空闲")

        ttk.Label(status_frame, text="POE2 前台:").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(status_frame, textvariable=self.poe_var, foreground="#22c55e").grid(
            row=0, column=1, sticky=tk.W, padx=(4, 20)
        )
        ttk.Label(status_frame, text="背包标定:").grid(row=0, column=2, sticky=tk.W)
        ttk.Label(status_frame, textvariable=self.cal_var, foreground="#38bdf8").grid(
            row=0, column=3, sticky=tk.W, padx=(4, 20)
        )
        ttk.Label(status_frame, text="整理状态:").grid(row=0, column=4, sticky=tk.W)
        ttk.Label(status_frame, textvariable=self.dump_var, foreground="#f59e0b").grid(
            row=0, column=5, sticky=tk.W, padx=(4, 0)
        )

    def _build_tabs(self) -> None:
        """四模块标签页。"""
        notebook = ttk.Notebook(self.root)
        notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=8)

        self.bag_tab = BagTab(notebook, log=self.log, on_hotkey_changed=self.register_hotkeys)
        notebook.add(self.bag_tab, text="背包整理")
        notebook.add(CombatTab(notebook), text="战斗")
        notebook.add(PlaceholderTab(notebook, "地图"), text="地图")
        notebook.add(PlaceholderTab(notebook, "装备"), text="装备")

    def _build_log(self) -> None:
        """共享日志区。"""
        log_frame = ttk.LabelFrame(self.root, text="日志", padding=8)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

        self.log_text = scrolledtext.ScrolledText(
            log_frame,
            wrap=tk.WORD,
            height=8,
            font=("Consolas", 10),
            bg="#0f172a",
            fg="#e2e8f0",
            insertbackground="#e2e8f0",
        )
        self.log_text.pack(fill=tk.BOTH, expand=True)

    # ============================================================
    # 日志输出（线程安全）
    # ============================================================
    def log(self, message: str) -> None:
        """向日志区追加消息；可从任意线程调用。"""
        timestamp = time.strftime("%H:%M:%S")
        full = f"[{timestamp}] {message}"

        def append() -> None:
            self.log_text.insert(tk.END, full + "\n")
            self.log_text.see(tk.END)

        self.root.after(0, append)

    # ============================================================
    # 热键注册
    # ============================================================
    def register_hotkeys(self) -> None:
        """按当前配置注册全部全局热键，重复调用会先移除旧热键。"""
        for handler in self.hotkey_handlers.values():
            try:
                keyboard.remove_hotkey(handler)
            except Exception:
                pass
        self.hotkey_handlers.clear()

        self.hotkey_handlers["dump"] = keyboard.add_hotkey(bag.get_dump_hotkey(), self.start_dump)
        self.hotkey_handlers["cal1"] = keyboard.add_hotkey(
            CALIBRATE_KEY_FIRST, lambda: bag.calibrate_point(1, logger=self.log)
        )
        self.hotkey_handlers["cal2"] = keyboard.add_hotkey(
            CALIBRATE_KEY_SECOND, lambda: bag.calibrate_point(2, logger=self.log)
        )
        self.hotkey_handlers["stop"] = keyboard.add_hotkey(STOP_HOTKEY, self.emergency_stop)

    # ============================================================
    # 状态刷新
    # ============================================================
    def update_status(self) -> None:
        """定时刷新界面状态。"""
        self.poe_var.set("是" if common.is_poe_active() else "否")
        self.cal_var.set("已标定" if bag.get_grid_config() is not None else "未标定")
        self.dump_var.set("运行中" if common.running else "空闲")
        self.root.after(500, self.update_status)

    # ============================================================
    # 动作
    # ============================================================
    def start_dump(self) -> None:
        """启动一键存仓；运行中再次触发则停止。"""
        if common.running:
            common.stop_event.set()
            self.log("停止整理背包")
            return
        if not common.is_poe_active():
            self.log("错误：POE2 未处于前台")
            return
        if bag.get_grid_config() is None:
            self.log("错误：尚未标定格子间距，请在游戏中按 F3/F4 标定相邻两格")
            return

        threading.Thread(target=bag.dump_bag, kwargs={"logger": self.log}, daemon=True).start()
        self.log("开始整理背包")

    def emergency_stop(self) -> None:
        """F12：停止所有任务并释放按键。"""
        common.emergency_stop(logger=self.log)

    # ============================================================
    # 退出清理
    # ============================================================
    def on_close(self) -> None:
        """关闭窗口时释放资源。"""
        self.log("正在退出…")
        common.emergency_stop()

        try:
            keyboard.unhook_all()
        except Exception:
            pass

        self.root.destroy()


def run_app() -> None:
    """主入口。"""
    try:
        root = tk.Tk()
        Poe2ToolsApp(root)
        root.mainloop()
    except Exception as exc:
        print(f"\n启动 GUI 失败: {exc}", file=sys.stderr)
        sys.exit(1)
