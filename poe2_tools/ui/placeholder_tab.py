import tkinter as tk
from tkinter import ttk


class PlaceholderTab(ttk.Frame):
    """尚未开发模块的占位页。"""

    def __init__(self, master: tk.Misc, module_name: str) -> None:
        super().__init__(master, padding=16)
        ttk.Label(self, text=f"{module_name}模块待开发", font=("", 12)).pack(pady=24)
