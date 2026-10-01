#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口与应用控制器：状态区 + 配置标签页 + 功能设置区 + 日志区。

职责：
- 启动时按需迁移旧版 AHK 配置并加载 Settings
- 构造业务模块（背包整理/石碑速点/地图速点/战斗宏），日志经 bus 汇入日志区
- 注册全局热键：战斗/整理/石碑/地图（仅 POE2 前台生效）、F3/F4 背包标定、
  F5 记录货币与旋风 Q/E 标定点、F12 全局急停
- 「保存配置」把控件值校验夹取后写回 ini 并重注册热键
"""

from __future__ import annotations

import platform
import sys
import time

# ============================================================
# 平台检查
# ============================================================
if platform.system() != "Windows":
    print("本工具仅能在 Windows 原生环境下运行。")
    sys.exit(1)

import tkinter as tk
from tkinter import scrolledtext, ttk

import cv2

from poe2_tools.bridge.bus import bus
from poe2_tools.config.migrate import merge_ahk_coords_file, migrate_file
from poe2_tools.config.settings import (
    CYCLONE_PROFILE,
    EMERGENCY_HOTKEY,
    INI_PATH,
    PROFILE_COUNT,
    CURRENCY_NAMES,
    Settings,
    load_settings,
    save_settings,
)
from poe2_tools.core import input as core_input
from poe2_tools.core import vision, window
from poe2_tools.core.hotkey import HotkeyManager
from poe2_tools.modules.bag import BagOrganizer
from poe2_tools.modules.combat import TEMPLATES_DIR, CombatMacro
from poe2_tools.modules.map_runner import MapRunner
from poe2_tools.modules.waystone import WaystoneRunner
from poe2_tools.ui.coords_tab import CoordsTab
from poe2_tools.ui.cyclone_tab import CycloneTab
from poe2_tools.ui.profile_tab import ProfileTab
from poe2_tools.ui.settings_panel import SettingsPanel

# 标定热键（固定）：F3/F4 背包格距，F5 记录货币/旋风标定点
CALIBRATE_KEY_FIRST = "f3"
CALIBRATE_KEY_SECOND = "f4"
CALIBRATE_KEY_RECORD = "f5"

# 状态轮询间隔
STATUS_POLL_MS = 500

# 旧版 AHK 配置路径（存在且新配置缺失时自动迁移）
AHK_INI_PATH = INI_PATH.parent / "ahk" / "poe2_key_helper.ini"


class Poe2ToolsApp:
    """Tkinter 主界面与控制器。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("POE2 游玩工具")
        self.root.geometry("960x680")
        self.root.minsize(920, 620)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._boot_logs: list[str] = []
        self.settings = self._load_or_migrate()
        self.hotkeys = HotkeyManager()
        self.pending_calib: str | None = None

        self.bag = BagOrganizer(self.settings, logger=bus.log, on_calibrated=self._on_bag_calibrated)
        self.waystone = WaystoneRunner(self.settings, self.bag, logger=bus.log)
        self.map_runner = MapRunner(self.settings, self.bag, logger=bus.log)
        self.combat = CombatMacro(self.settings, logger=bus.log)

        self._build_status()
        self._build_body()
        self._build_log()
        self.load_controls()

        bus.subscribe(self._on_bus_message)
        for message in self._boot_logs:
            self.log(message)

        self.register_hotkeys()
        self.log(
            f"控制台已启动。战斗: {self.settings.combat_hotkey.upper()}，"
            f"整理: {self.settings.dump_hotkey.upper()}，"
            f"石碑: {self.settings.way_hotkey.upper()}，"
            f"地图: {self.settings.map_hotkey.upper()}，"
            f"标定: F3/F4/F5，急停: {EMERGENCY_HOTKEY.upper()}"
        )

        # 标签页选中当前生效配置（配置1 / 旋风）
        profile_index = self.settings.active_profile - 1
        if 0 <= profile_index <= CYCLONE_PROFILE - 1:
            self.notebook.select(profile_index)

        self._poll_status()

    # ============================================================
    # 配置加载（含旧版迁移）
    # ============================================================
    def _load_or_migrate(self) -> Settings:
        """新配置缺失且存在旧版 AHK 配置时自动迁移，然后加载。"""
        if not INI_PATH.exists() and AHK_INI_PATH.exists():
            migrated = migrate_file(AHK_INI_PATH, INI_PATH)
            if migrated is not None:
                self._boot_logs.append("检测到旧版 AHK 配置，已自动迁移到 poe2_tools.ini")
                return migrated
        settings = load_settings()
        # 已有新配置但坐标缺失时，从旧版 AHK 配置增量同步坐标（不覆盖已有值）
        synced = merge_ahk_coords_file(settings, AHK_INI_PATH)
        if synced:
            save_settings(settings)
            names = "、".join(self._calib_name(target) for target in synced)
            self._boot_logs.append(f"已从旧版 AHK 配置同步坐标：{names}")
        self._boot_logs.append(f"已加载配置：{INI_PATH}")
        return settings

    # ============================================================
    # UI 构建
    # ============================================================
    def _build_status(self) -> None:
        """顶部运行状态区。"""
        frame = ttk.LabelFrame(self.root, text="运行状态", padding=6)
        frame.pack(fill=tk.X, padx=10, pady=(8, 0))

        self.poe_var = tk.StringVar(value="检测中…")
        self.combat_var = tk.StringVar(value="停止")
        self.bag_var = tk.StringVar(value="空闲")
        self.way_var = tk.StringVar(value="空闲")
        self.map_var = tk.StringVar(value="空闲")
        self.profile_var = tk.StringVar(value="配置1")

        items = [
            ("POE2 前台", self.poe_var, "#22c55e"),
            ("战斗", self.combat_var, "#f472b6"),
            ("整理", self.bag_var, "#f59e0b"),
            ("石碑", self.way_var, "#f59e0b"),
            ("地图", self.map_var, "#f59e0b"),
            ("当前配置", self.profile_var, "#38bdf8"),
        ]
        for col, (label, var, color) in enumerate(items):
            ttk.Label(frame, text=f"{label}:").grid(row=0, column=col * 2, sticky=tk.W)
            ttk.Label(frame, textvariable=var, foreground=color).grid(
                row=0, column=col * 2 + 1, sticky=tk.W, padx=(4, 16)
            )

    def _build_body(self) -> None:
        """中部：左侧标签页 + 右侧功能设置区。"""
        body = ttk.Frame(self.root)
        body.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        self.notebook = ttk.Notebook(body)
        self.notebook.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        self.profile_tabs: list[ProfileTab] = []
        for i in range(PROFILE_COUNT):
            tab = ProfileTab(self.notebook, i + 1)
            self.notebook.add(tab, text=f"配置{i + 1}")
            self.profile_tabs.append(tab)
        self.cyclone_tab = CycloneTab(
            self.notebook,
            on_calibrate=self.toggle_calibration,
            on_screenshot=self.grab_template,
        )
        self.notebook.add(self.cyclone_tab, text="旋风")
        self.coords_tab = CoordsTab(self.notebook, on_calibrate=self.toggle_calibration)
        self.notebook.add(self.coords_tab, text="坐标")
        self.notebook.bind("<<NotebookTabChanged>>", self._on_tab_changed)

        self.settings_panel = SettingsPanel(body, on_save=self.save_config)
        self.settings_panel.pack(side=tk.RIGHT, fill=tk.Y, padx=(8, 0))

    def _build_log(self) -> None:
        """底部日志区。"""
        log_frame = ttk.LabelFrame(self.root, text="日志", padding=6)
        log_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 8))

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
    # 控件 <-> 配置同步
    # ============================================================
    def load_controls(self) -> None:
        """把配置载入全部控件。"""
        for i, tab in enumerate(self.profile_tabs):
            tab.load_from(self.settings.profiles[i])
        self.cyclone_tab.load_from(self.settings)
        self.coords_tab.refresh_coords(self.settings)
        self.settings_panel.load_from(self.settings)

    def sync_controls(self) -> None:
        """把控件值同步回内存配置（含校验夹取）。"""
        for i, tab in enumerate(self.profile_tabs):
            tab.sync_to(self.settings.profiles[i])
        self.cyclone_tab.sync_to(self.settings)
        self.settings_panel.sync_to(self.settings)

    def _on_tab_changed(self, _event: tk.Event) -> None:
        """切换标签页：同步控件值，active_profile 跟随标签页（坐标页除外）。"""
        self.sync_controls()
        index = self.notebook.index(self.notebook.select())
        if 0 <= index <= CYCLONE_PROFILE - 1:
            self.settings.active_profile = index + 1

    # ============================================================
    # 日志（线程安全）
    # ============================================================
    def log(self, message: str) -> None:
        """向日志区追加消息；可从任意线程调用。"""
        full = f"[{time.strftime('%H:%M:%S')}] {message}"

        def append() -> None:
            self.log_text.insert(tk.END, full + "\n")
            self.log_text.see(tk.END)

        try:
            self.root.after(0, append)
        except RuntimeError:
            pass  # 窗口已销毁

    def _on_bus_message(self, message: dict) -> None:
        """订阅 bus：把模块日志汇入日志区。"""
        if message.get("type") == "log":
            self.log(str(message.get("message", "")))

    # ============================================================
    # 热键注册
    # ============================================================
    def register_hotkeys(self) -> None:
        """按当前配置注册全部热键；重复调用先清理旧热键。"""
        s = self.settings
        self.hotkeys.register_when_poe_active(
            "combat", s.combat_hotkey, self.combat.toggle, window.is_poe_active
        )
        self.hotkeys.register_when_poe_active(
            "bag", s.dump_hotkey, self.bag.toggle, window.is_poe_active
        )
        self.hotkeys.register_when_poe_active(
            "waystone", s.way_hotkey, self.waystone.toggle, window.is_poe_active
        )
        self.hotkeys.register_when_poe_active(
            "map", s.map_hotkey, self.map_runner.toggle, window.is_poe_active
        )
        self.hotkeys.register_when_poe_active(
            "cal_first", CALIBRATE_KEY_FIRST, self.bag.calibrate_first, window.is_poe_active
        )
        self.hotkeys.register_when_poe_active(
            "cal_second", CALIBRATE_KEY_SECOND, self.bag.calibrate_second, window.is_poe_active
        )
        self.hotkeys.register_when_poe_active(
            "cal_record", CALIBRATE_KEY_RECORD, self._record_pending_calibration,
            window.is_poe_active,
        )
        self.hotkeys.register("emergency", EMERGENCY_HOTKEY, self.emergency_stop)

    # ============================================================
    # 标定流程（货币 + 旋风 Q/E）
    # ============================================================
    @staticmethod
    def _calib_name(target: str) -> str:
        """待标定目标的中文名（如 currency:alch -> 点金石）。"""
        kind, key = target.split(":", 1)
        if kind == "currency":
            return CURRENCY_NAMES.get(key, key)
        return f"旋风 {key.upper()} 数字检测"

    def toggle_calibration(self, target: str) -> None:
        """「标定」按钮：进入/取消待标定状态，等待游戏内按 F5 记录。"""
        if self.pending_calib == target:
            self.pending_calib = None
            self.log(f"已取消标定「{self._calib_name(target)}」")
        else:
            self.pending_calib = target
            self.log(
                f"标定「{self._calib_name(target)}」：请切换到游戏，"
                f"将鼠标指向目标后按 {CALIBRATE_KEY_RECORD.upper()} 记录；再次点击按钮取消"
            )
        self._refresh_calib_buttons()

    def _record_pending_calibration(self) -> None:
        """F5 回调（键盘线程，POE2 前台时触发）：记录待标定点坐标。"""
        target = self.pending_calib
        if target is None:
            self.log(
                f"当前没有待标定项：请在「旋风」或「坐标」页点击「标定」后再按 "
                f"{CALIBRATE_KEY_RECORD.upper()}"
            )
            return
        pos = window.cursor_client_pos()
        if pos is None:
            self.log("标定失败：未找到 POE2 窗口")
            return
        kind, key = target.split(":", 1)
        if kind == "currency":
            self.settings.currency[key] = pos
        else:
            self.settings.cyclone_coords[key] = pos
        save_settings(self.settings)
        self.pending_calib = None
        self.log(f"已标定「{self._calib_name(target)}」({pos.x}, {pos.y})")
        self.root.after(0, self._refresh_after_calibration)

    def _refresh_after_calibration(self) -> None:
        """标定完成后刷新坐标显示与按钮状态（主线程）。"""
        self.cyclone_tab.refresh_coords(self.settings)
        self.coords_tab.refresh_coords(self.settings)
        self._refresh_calib_buttons()

    def _refresh_calib_buttons(self) -> None:
        """根据待标定状态刷新两页的「标定/取消」按钮文案。"""
        self.cyclone_tab.set_pending(self.pending_calib)
        self.coords_tab.set_pending(self.pending_calib)

    def _on_bag_calibrated(self) -> None:
        """背包 F4 标定成功回调（键盘线程）：刷新格子间距显示。"""
        self.root.after(0, lambda: self.settings_panel.set_cell_size(self.settings.cell_size))

    # ============================================================
    # 旋风模板截图
    # ============================================================
    def grab_template(self, key: str) -> None:
        """「截图」按钮：在旋风 Q/E 标定点截取模板图。"""
        point = self.settings.cyclone_coords.get(key)
        if point is None:
            self.log(f"请先标定「旋风 {key.upper()} 数字检测」坐标再截图")
            return
        image = vision.grab_template_image(point)
        if image is None:
            self.log("截图失败：未找到 POE2 窗口")
            return
        TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
        path = TEMPLATES_DIR / f"{key}.png"
        cv2.imwrite(str(path), image)
        self.log(f"旋风 {key.upper()} 模板图已保存：{path}")

    # ============================================================
    # 状态轮询
    # ============================================================
    def _profile_name(self) -> str:
        if self.settings.active_profile == CYCLONE_PROFILE:
            return "旋风"
        return f"配置{self.settings.active_profile}"

    def _poll_status(self) -> None:
        """定时刷新状态区与各页坐标显示。"""
        self.poe_var.set("是" if window.is_poe_active() else "否")
        self.combat_var.set("运行" if self.combat.active else "停止")
        self.bag_var.set("整理中" if self.bag.running else "空闲")
        self.way_var.set("速点中" if self.waystone.running else "空闲")
        self.map_var.set("速点中" if self.map_runner.running else "空闲")
        self.profile_var.set(self._profile_name())
        self.settings_panel.set_cell_size(self.settings.cell_size)
        self.cyclone_tab.refresh_coords(self.settings)
        self.coords_tab.refresh_coords(self.settings)
        self.root.after(STATUS_POLL_MS, self._poll_status)

    # ============================================================
    # 动作
    # ============================================================
    def save_config(self) -> None:
        """「保存配置」：同步控件值（含校验夹取）→ 写盘 → 重注册热键。"""
        self.sync_controls()
        save_settings(self.settings)
        self.load_controls()  # 回显夹取后的值
        self.register_hotkeys()
        self.log("配置已保存，热键已生效")

    def emergency_stop(self) -> None:
        """F12：中断全部任务并释放所有按键。"""
        self.bag.request_stop()
        self.waystone.request_stop()
        self.map_runner.request_stop()
        self.combat.stop()
        core_input.release_all()
        self.log("已紧急停止：全部任务中断，所有按键已释放")

    # ============================================================
    # 退出清理
    # ============================================================
    def on_close(self) -> None:
        """关闭窗口：保存配置 + 急停 + 注销热键。"""
        self.log("正在退出…")
        self.sync_controls()
        try:
            save_settings(self.settings)
        except Exception:
            pass
        self.emergency_stop()
        self.hotkeys.unregister_all()
        bus.unsubscribe(self._on_bus_message)
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
