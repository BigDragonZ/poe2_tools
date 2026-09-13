import tkinter as tk
from tkinter import ttk


class BagTab(ttk.Frame):
    """背包整理：热键与网格设置，功能逻辑待从 poe1_tools 迁移后接入。"""

    def __init__(self, master: tk.Misc) -> None:
        super().__init__(master, padding=16)

        hotkey_frame = ttk.LabelFrame(self, text="热键设置", padding=8)
        hotkey_frame.pack(fill=tk.X)
        ttk.Label(hotkey_frame, text="整理热键：").grid(row=0, column=0, sticky=tk.W)
        self.dump_hotkey = ttk.Entry(hotkey_frame, width=10)
        self.dump_hotkey.insert(0, "F1")
        self.dump_hotkey.grid(row=0, column=1, sticky=tk.W)

        grid_frame = ttk.LabelFrame(self, text="背包设置", padding=8)
        grid_frame.pack(fill=tk.X, pady=(8, 0))
        ttk.Label(grid_frame, text="行数：").grid(row=0, column=0, sticky=tk.W)
        self.rows = ttk.Entry(grid_frame, width=6)
        self.rows.insert(0, "5")
        self.rows.grid(row=0, column=1, sticky=tk.W)
        ttk.Label(grid_frame, text="列数：").grid(row=0, column=2, sticky=tk.W, padx=(16, 0))
        self.cols = ttk.Entry(grid_frame, width=6)
        self.cols.insert(0, "11")
        self.cols.grid(row=0, column=3, sticky=tk.W)

        ttk.Label(
            self,
            text="标定与执行功能待迁移 poe1_tools/poe_tools/bag.py 后接入",
            foreground="gray",
        ).pack(anchor=tk.W, pady=(8, 0))
        ttk.Button(self, text="保存背包设置", command=self._on_save).pack(anchor=tk.E, pady=(8, 0))

    def _on_save(self) -> None:
        # 待功能迁移后写入配置文件
        pass
