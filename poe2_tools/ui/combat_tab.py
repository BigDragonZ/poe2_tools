#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""战斗页：启停热键与各按键策略/间隔设置。"""

from __future__ import annotations

import threading
import tkinter as tk
from collections.abc import Callable
from tkinter import ttk

import keyboard

from poe2_tools import combat

# 策略显示名 -> 内部标识
MODE_NAME_TO_ID = {name: mode for mode, name in combat.MODES}


class CombatTab(ttk.Frame):
    """战斗巡航模块界面。"""

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
        self.skill_widgets: list[tuple[str, tk.StringVar, tk.StringVar]] = []

        # ---------- 热键设置 ----------
        hotkey_frame = ttk.LabelFrame(self, text="热键设置", padding=8)
        hotkey_frame.pack(fill=tk.X)

        self.toggle_hotkey_var = tk.StringVar(value=combat.get_toggle_hotkey())
        ttk.Label(hotkey_frame, text="启停热键：").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(
            hotkey_frame,
            textvariable=self.toggle_hotkey_var,
            foreground="#a855f7",
            font=("Consolas", 10, "bold"),
        ).grid(row=0, column=1, sticky=tk.W, padx=(4, 8))
        self.btn_capture = ttk.Button(hotkey_frame, text="设置热键", command=self.capture_hotkey)
        self.btn_capture.grid(row=0, column=2, sticky=tk.W)

        # ---------- 战斗设置 ----------
        keys_frame = ttk.LabelFrame(self, text="战斗设置", padding=8)
        keys_frame.pack(fill=tk.X, pady=(8, 0))

        ttk.Label(keys_frame, text="按键", foreground="#64748b").grid(row=0, column=0, sticky=tk.W)
        ttk.Label(keys_frame, text="策略", foreground="#64748b").grid(row=0, column=1, sticky=tk.W, padx=(12, 0))
        ttk.Label(keys_frame, text="间隔(ms)", foreground="#64748b").grid(row=0, column=2, sticky=tk.W, padx=(12, 0))

        skills = combat.load_skills()
        key_names = dict(combat.KEYS)
        mode_names = [name for _, name in combat.MODES]
        for row, skill in enumerate(skills, start=1):
            ttk.Label(keys_frame, text=key_names[skill.key_id]).grid(row=row, column=0, sticky=tk.W, pady=2)

            mode_var = tk.StringVar(value=dict(combat.MODES)[skill.mode])
            ttk.Combobox(
                keys_frame, textvariable=mode_var, values=mode_names, state="readonly", width=8
            ).grid(row=row, column=1, sticky=tk.W, padx=(12, 0), pady=2)

            interval_var = tk.StringVar(value=str(skill.interval_ms))
            ttk.Spinbox(
                keys_frame,
                from_=combat.MIN_INTERVAL_MS,
                to=60000,
                increment=50,
                textvariable=interval_var,
                width=8,
            ).grid(row=row, column=2, sticky=tk.W, padx=(12, 0), pady=2)

            self.skill_widgets.append((skill.key_id, mode_var, interval_var))

        ttk.Button(keys_frame, text="保存战斗设置", command=self.save_combat).grid(
            row=len(skills) + 1, column=0, columnspan=3, sticky=tk.W, pady=(8, 0)
        )

    # ============================================================
    # 热键捕获
    # ============================================================
    def capture_hotkey(self) -> None:
        """进入热键捕获模式：按下任意键作为新启停热键，Esc 取消。"""
        if self.capturing:
            return
        self.capturing = True
        self.btn_capture.config(state=tk.DISABLED)
        self.log("请按下新的战斗启停热键…（按 Esc 取消）")
        threading.Thread(target=self._capture_worker, daemon=True).start()

    def _capture_worker(self) -> None:
        """在后台线程等待按键并保存。"""
        key = keyboard.read_key()
        if key == "esc":
            self.log("已取消热键设置。")
        else:
            combat.set_toggle_hotkey(key)
            self.log(f"战斗启停热键已设置为: {key}")
            self.after(0, self.on_hotkey_changed)
            self.after(0, lambda: self.toggle_hotkey_var.set(key))

        def restore() -> None:
            self.capturing = False
            self.btn_capture.config(state=tk.NORMAL)

        self.after(0, restore)

    # ============================================================
    # 战斗设置保存
    # ============================================================
    def save_combat(self) -> None:
        """把界面上的战斗配置写入 poe2_tools.ini。"""
        skills: list[combat.SkillConfig] = []
        for key_id, mode_var, interval_var in self.skill_widgets:
            mode = MODE_NAME_TO_ID.get(mode_var.get(), "disabled")
            try:
                interval = int(interval_var.get())
            except ValueError:
                interval = combat.DEFAULT_INTERVAL_MS
            interval = max(interval, combat.MIN_INTERVAL_MS)
            interval_var.set(str(interval))
            skills.append(combat.SkillConfig(key_id, mode, interval))

        combat.save_skills(skills)
        enabled = [s for s in skills if s.mode != "disabled"]
        if enabled:
            names = dict(combat.KEYS)
            self.log("战斗设置已保存: " + ", ".join(f"{names[s.key_id]}({s.mode})" for s in enabled))
        else:
            self.log("战斗设置已保存（全部禁用）")
