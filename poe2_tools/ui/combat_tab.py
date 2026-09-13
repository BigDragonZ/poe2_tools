import tkinter as tk
from tkinter import ttk

KEYS = ["鼠标左键", "鼠标右键", "空格", "Q", "W", "E", "R"]
STRATEGIES = ["禁用", "连点", "按住不放"]


class CombatTab(ttk.Frame):
    """战斗巡航：各按键策略与间隔设置，功能逻辑待从 poe1_tools 迁移后接入。"""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=16)

        hotkey_frame = ttk.LabelFrame(self, text="热键设置", padding=8)
        hotkey_frame.pack(fill=tk.X)
        ttk.Label(hotkey_frame, text="启停热键：").grid(row=0, column=0, sticky=tk.W)
        self.toggle_key = ttk.Entry(hotkey_frame, width=10)
        self.toggle_key.insert(0, "F2")
        self.toggle_key.grid(row=0, column=1, sticky=tk.W)

        keys_frame = ttk.LabelFrame(self, text="战斗设置", padding=8)
        keys_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(keys_frame, text="按键").grid(row=0, column=0, padx=4)
        ttk.Label(keys_frame, text="策略").grid(row=0, column=1, padx=4)
        ttk.Label(keys_frame, text="间隔(ms)").grid(row=0, column=2, padx=4)

        self.key_strategy: dict[str, ttk.Combobox] = {}
        self.key_interval: dict[str, ttk.Entry] = {}
        for i, key in enumerate(KEYS, start=1):
            ttk.Label(keys_frame, text=key).grid(row=i, column=0, sticky=tk.W, padx=4, pady=2)
            strategy = ttk.Combobox(keys_frame, values=STRATEGIES, width=8, state="readonly")
            strategy.set("禁用")
            strategy.grid(row=i, column=1, padx=4, pady=2)
            interval = ttk.Entry(keys_frame, width=8)
            interval.insert(0, "300")
            interval.grid(row=i, column=2, padx=4, pady=2)
            self.key_strategy[key] = strategy
            self.key_interval[key] = interval

        ttk.Label(
            self,
            text="执行逻辑待迁移 poe1_tools/poe_tools/combat.py 后接入",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(8, 0))
        ttk.Button(self, text="保存战斗设置", command=self._on_save).pack(anchor=tk.E, pady=(8, 0))

    def _on_save(self) -> None:
        # 待功能迁移后写入配置文件
        pass
