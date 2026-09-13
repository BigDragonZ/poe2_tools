import tkinter as tk
from tkinter import ttk

from poe2_tools.ui.bag_tab import BagTab
from poe2_tools.ui.combat_tab import CombatTab
from poe2_tools.ui.placeholder_tab import PlaceholderTab


def run_app() -> None:
    root = tk.Tk()
    root.title("POE2 游玩工具")
    root.geometry("560x480")

    notebook = ttk.Notebook(root)
    notebook.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

    notebook.add(BagTab(notebook), text="背包整理")
    notebook.add(CombatTab(notebook), text="战斗")
    notebook.add(PlaceholderTab(notebook, "地图"), text="地图")
    notebook.add(PlaceholderTab(notebook, "装备"), text="装备")

    root.mainloop()
