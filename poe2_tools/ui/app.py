#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
主窗口与应用控制器：Header 状态区 + StackedView 四模块 + 底部导航 + 日志面板。

布局：
- Header：POE2 前台 | 战斗/整理/石碑/地图状态 | 当前配置 | 当前模块 | 「急停: F12」常驻提示
- Nav：模块导航栏（战斗 / 通用 / 研发 / 交易，位于运行状态区下方，选中态高亮）
- Main View：StackedView 四模块切换（战斗 / 通用 / 研发 / 交易）
- Log Panel：可折叠，按级别着色，随 dev.log_level/debug 过滤

职责：
- 启动时按需迁移旧版 AHK 配置并加载 Settings
- 构造业务模块（背包整理/石碑速点/地图速点/战斗宏/刷图/输入记录），日志经 bus 汇入日志面板
- 注册全局热键：战斗/整理/石碑/地图/F3/F4（功能热键，POE2 前台即生效，作用于当前
  激活配置）、F5 标定（旋风/坐标/开发页）、F2 测试页输入记录（仅测试页）、F12 全局急停；
  功能热键与当前页动作键同键时动作键优先；页不对时按动作键会在日志提示归属页
- 「保存配置」把控件值校验夹取后写回 ini 并重注册热键，同时应用日志过滤
"""

from __future__ import annotations

import platform
import sys
from collections.abc import Callable

# ============================================================
# 平台检查
# ============================================================
if platform.system() != "Windows":
    print("本工具仅能在 Windows 原生环境下运行。")
    sys.exit(1)

import tkinter as tk
from tkinter import ttk

from poe2_tools.bridge.bus import bus
from poe2_tools.config.migrate import merge_ahk_coords_file, migrate_file
from poe2_tools.config.settings import (
    CYCLONE_PROFILE,
    EMERGENCY_HOTKEY,
    INI_PATH,
    CURRENCY_NAMES,
    Point,
    Settings,
    load_settings,
    save_settings,
)
from poe2_tools.core import input as core_input
from poe2_tools.core import window
from poe2_tools.core.hotkey import HotkeyManager
from poe2_tools.modules.bag import BagOrganizer
from poe2_tools.modules.combat import CombatMacro
from poe2_tools.modules.map_runner import MapRunner
from poe2_tools.modules.mapping.assistant import MappingAssistant
from poe2_tools.modules.market.scanner import CurrencyTradeScanner
from poe2_tools.modules.mapping.calibrate import (
    CalibrateError,
    Q6MarkSession,
    capture_template,
    normalize_roi,
)
from poe2_tools.modules.measure import MeasureError, RangeMarkSession, normalize_range
from poe2_tools.modules.recorder.recorder import InputRecorder
from poe2_tools.modules.waystone import WaystoneRunner
from poe2_tools.ui.combat_module import CombatModule
from poe2_tools.ui.dev_module import DevModule
from poe2_tools.ui.general_module import GeneralModule
from poe2_tools.ui.log_panel import LogPanel
from poe2_tools.ui.stacked import StackedView
from poe2_tools.ui.trade_module import TradeModule

# 标定热键（固定）：F3/F4 背包格距，F5 记录货币/旋风标定点
CALIBRATE_KEY_FIRST = "f3"
CALIBRATE_KEY_SECOND = "f4"
CALIBRATE_KEY_RECORD = "f5"

# 输入记录热键（固定）：F2 开始/停止一轮
RECORDER_KEY = "f2"

# 模块（导航栏）id 与显示名，按导航顺序
MODULES = (("combat", "战斗"), ("general", "通用"), ("dev", "研发"), ("trade", "交易"))
MODULE_NAMES = dict(MODULES)

# 页面级作用域 id（当前模块, 模块内子页）→ 显示名
SCOPE_NAMES = {
    "profile": "配置",
    "cyclone": "旋风",
    "sort": "整理",
    "tablet": "石碑",
    "map": "地图",
    "dev": "开发",
    "test": "测试",
    "coords": "坐标",
    "trade": "交易",
}

# 页面级动作键（归属页 → 键位）：功能热键与当前页动作键同键时，动作键优先
PAGE_ACTION_KEYS = {
    "cyclone": frozenset({CALIBRATE_KEY_RECORD}),
    "coords": frozenset({CALIBRATE_KEY_RECORD}),
    "test": frozenset({RECORDER_KEY}),
    "dev": frozenset({CALIBRATE_KEY_RECORD}),
}

# 状态轮询间隔
STATUS_POLL_MS = 500

# 刷图助手「启动」后等待 POE2 前台的轮询参数（点按钮时焦点在工具窗口，
# 必然非前台，需等用户切回游戏再自动启动）
MAPPING_START_POLL_MS = 500
MAPPING_START_TIMEOUT_MS = 15000

# 旧版 AHK 配置路径（存在且新配置缺失时自动迁移）
AHK_INI_PATH = INI_PATH.parent / "ahk" / "poe2_key_helper.ini"

# 底部导航按钮配色（选中态高亮）
NAV_BG = "#1e293b"
NAV_FG = "#e2e8f0"
NAV_ACTIVE_BG = "#38bdf8"
NAV_ACTIVE_FG = "#0f172a"


class Poe2ToolsApp:
    """Tkinter 主界面与控制器。"""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("POE2 游玩工具")
        self.root.geometry("1180x720")
        self.root.minsize(1120, 660)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

        self._boot_logs: list[str] = []
        self.settings = self._load_or_migrate()
        self.hotkeys = HotkeyManager()
        self.pending_calib: str | None = None
        self._q6_marker: Q6MarkSession | None = None
        self._range_marker: RangeMarkSession | None = None
        self._mapping_start_gen = 0  # 待启动轮询换代计数（停止/重复点启动时作废旧轮询）
        # 当前模块与页面作用域（仅主线程写，热键回调线程只读，避免在热键线程触碰 tk）
        self._current_module = "combat"
        self._scope = "profile"

        self.bag = BagOrganizer(self.settings, logger=bus.log, on_calibrated=self._on_bag_calibrated)
        self.waystone = WaystoneRunner(self.settings, self.bag, logger=bus.log)
        self.map_runner = MapRunner(self.settings, self.bag, logger=bus.log)
        self.combat = CombatMacro(self.settings, logger=bus.log)
        self.mapping = MappingAssistant(self.settings, logger=bus.log)
        self.recorder = InputRecorder(logger=bus.log)
        self.market_scanner = CurrencyTradeScanner(self.settings, logger=bus.log)

        self._build_header()
        self._build_nav()
        self._build_log()
        self._build_body()
        self.load_controls()

        bus.subscribe(self._on_bus_message)
        for message in self._boot_logs:
            self.log(message)

        self.register_hotkeys()
        self.log(
            f"控制台已启动。战斗: {self.settings.combat.hotkey.upper()}，"
            f"整理: {self.settings.general.sort.hotkey.upper()}，"
            f"石碑: {self.settings.general.tablet.hotkey.upper()}，"
            f"地图: {self.settings.general.map_click.hotkey.upper()}，"
            f"市场抓取: {self.settings.market_scan.hotkey.upper()}，"
            f"默认通货: {self.settings.market_scan.hotkey_default.upper()}，"
            f"指定通货: {self.settings.market_scan.hotkey_custom.upper()}，"
            f"标定: F3/F4/F5，记录: {RECORDER_KEY.upper()}，急停: {EMERGENCY_HOTKEY.upper()}"
            "（功能热键作用于当前激活配置，标定/记录各归其页）"
        )

        # 默认选中战斗模块，并按激活配置选内嵌子页（配置1 / 旋风）
        profile_index = self.settings.combat.active_profile - 1
        if 0 <= profile_index <= CYCLONE_PROFILE - 1:
            self.combat_module.select_page(profile_index)
        self._switch_module("combat")
        self._sync_scope()

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
    def _build_header(self) -> None:
        """顶部 Header：运行状态 + 当前模块 + 急停提示。"""
        frame = ttk.LabelFrame(self.root, text="运行状态", padding=6)
        frame.pack(fill=tk.X, padx=10, pady=(8, 0))

        self.poe_var = tk.StringVar(value="检测中…")
        self.combat_var = tk.StringVar(value="停止")
        self.bag_var = tk.StringVar(value="空闲")
        self.way_var = tk.StringVar(value="空闲")
        self.map_var = tk.StringVar(value="空闲")
        self.profile_var = tk.StringVar(value="配置1")
        self.module_var = tk.StringVar(value=MODULE_NAMES["combat"])

        items = [
            ("POE2 前台", self.poe_var, "#22c55e"),
            ("战斗", self.combat_var, "#f472b6"),
            ("整理", self.bag_var, "#f59e0b"),
            ("石碑", self.way_var, "#f59e0b"),
            ("地图", self.map_var, "#f59e0b"),
            ("当前配置", self.profile_var, "#38bdf8"),
            ("当前模块", self.module_var, "#a78bfa"),
        ]
        for col, (label, var, color) in enumerate(items):
            ttk.Label(frame, text=f"{label}:").grid(row=0, column=col * 2, sticky=tk.W)
            ttk.Label(frame, textvariable=var, foreground=color).grid(
                row=0, column=col * 2 + 1, sticky=tk.W, padx=(4, 16)
            )
        ttk.Label(
            frame,
            text=f"急停: {EMERGENCY_HOTKEY.upper()}",
            foreground="#ef4444",
            font=("", 10, "bold"),
        ).grid(row=0, column=len(items) * 2, sticky=tk.W, padx=(8, 0))

    def _build_body(self) -> None:
        """中部 Main View：StackedView 四模块。"""
        self.stacked = StackedView(self.root)
        self.stacked.pack(fill=tk.BOTH, expand=True, padx=10, pady=8)

        self.combat_module = CombatModule(
            self.stacked,
            on_page_change=self._on_page_changed,
            on_save=self.save_config,
            on_calibrate=self.toggle_calibration,
            on_mapping_start=self._mapping_start,
            on_mapping_stop=self._mapping_stop,
        )
        self.general_module = GeneralModule(
            self.stacked,
            on_page_change=self._on_page_changed,
            on_save=self.save_config,
        )
        self.dev_module = DevModule(
            self.stacked,
            on_page_change=self._on_page_changed,
            on_save=self.save_config,
            on_calibrate=self.toggle_calibration,
            recorder=self.recorder,
        )
        self.trade_module = TradeModule(
            self.stacked, scanner=self.market_scanner, on_save=self.save_config,
            logger=bus.log,
        )

        self.stacked.add("combat", self.combat_module)
        self.stacked.add("general", self.general_module)
        self.stacked.add("dev", self.dev_module)
        self.stacked.add("trade", self.trade_module)
        # 模块引用表：_sync_scope 按当前模块取子页
        self._modules = {
            "combat": self.combat_module,
            "general": self.general_module,
            "dev": self.dev_module,
        }

    def _build_nav(self) -> None:
        """顶部导航栏（运行状态区之下、内容区之上）：四模块切换按钮，选中态高亮。"""
        nav = ttk.Frame(self.root)
        nav.pack(fill=tk.X, padx=10, pady=(8, 0))
        self._nav_buttons: dict[str, tk.Button] = {}
        for name, label in MODULES:
            button = tk.Button(
                nav,
                text=label,
                width=14,
                relief=tk.RAISED,
                bg=NAV_BG,
                fg=NAV_FG,
                activebackground=NAV_ACTIVE_BG,
                activeforeground=NAV_ACTIVE_FG,
                command=lambda n=name: self._switch_module(n),
            )
            button.pack(side=tk.LEFT, expand=True, fill=tk.X, padx=(0, 6))
            self._nav_buttons[name] = button

    def _build_log(self) -> None:
        """日志面板（窗口最底部）：可折叠 + 级别着色 + 按 dev 配置过滤。"""
        self.log_panel = LogPanel(self.root)
        self.log_panel.pack(side=tk.BOTTOM, fill=tk.X, padx=10, pady=(0, 8))
        self.log_panel.set_filter(self.settings.dev.log_level, self.settings.dev.debug)

    def _switch_module(self, name: str) -> None:
        """导航栏切换模块：置顶页面 + 选中态高亮 + 更新当前模块显示与作用域。"""
        self._current_module = name
        self.stacked.show(name)
        for nav_name, button in self._nav_buttons.items():
            if nav_name == name:
                button.config(relief=tk.SUNKEN, bg=NAV_ACTIVE_BG, fg=NAV_ACTIVE_FG)
            else:
                button.config(relief=tk.RAISED, bg=NAV_BG, fg=NAV_FG)
        self.module_var.set(MODULE_NAMES[name])
        self._on_page_changed()

    # ============================================================
    # 控件 <-> 配置同步
    # ============================================================
    def load_controls(self) -> None:
        """把配置载入全部模块控件。"""
        self.combat_module.load_from(self.settings)
        self.general_module.load_from(self.settings)
        self.dev_module.load_from(self.settings)
        self.trade_module.load_from(self.settings)

    def sync_controls(self) -> None:
        """把控件值同步回内存配置（含校验夹取）。"""
        self.combat_module.sync_to(self.settings)
        self.general_module.sync_to(self.settings)
        self.dev_module.sync_to(self.settings)
        self.trade_module.sync_to(self.settings)

    def _on_page_changed(self, _page_id: str | None = None) -> None:
        """模块子页切换 / 底部导航切换的统一入口。

        同步控件值；active_profile 跟随战斗模块子页（配置1=1，旋风=2=CYCLONE_PROFILE）。
        """
        self.sync_controls()
        self._sync_scope()
        if self._current_module == "combat":
            index = self.combat_module.notebook.index(self.combat_module.notebook.select())
            self.settings.combat.active_profile = index + 1

    def _sync_scope(self) -> None:
        """按（当前模块, 模块内子页）更新热键作用域（仅主线程写，热键回调线程只读）。"""
        module = self._modules.get(self._current_module)
        self._scope = module.current_page() if module is not None else "trade"

    def _function_guard(self, hotkey: str) -> Callable[[], bool]:
        """功能热键生效条件：POE2 前台；与当前页动作键同键时让位（动作键优先）。"""

        def check() -> bool:
            if not window.is_poe_active():
                return False
            if hotkey.strip().lower() in PAGE_ACTION_KEYS.get(self._scope, frozenset()):
                self.log(f"热键 {hotkey.upper()} 在当前页是动作键，对应功能不触发")
                return False
            return True

        return check

    def _register_scoped(
        self,
        name: str,
        hotkey: str,
        callback: Callable[[], None],
        scopes: tuple[str, ...],
        hint: str,
    ) -> None:
        """注册作用域热键：POE2 前台且当前页在 scopes 内才触发；页不对时日志提示。"""

        def _run() -> None:
            if not window.is_poe_active():
                return
            if self._scope not in scopes:
                self.log(f"{hint}（当前页：{SCOPE_NAMES.get(self._scope, self._scope)}）")
                return
            callback()

        self.hotkeys.register(name, hotkey, _run)

    # ============================================================
    # 日志（线程安全）
    # ============================================================
    def log(self, message: str, level: str = "INFO") -> None:
        """向日志面板追加消息；可从任意线程调用。"""
        self.log_panel.append(message, level)

    def _on_bus_message(self, message: dict) -> None:
        """订阅 bus：把模块日志汇入日志面板（默认 INFO 级）。"""
        if message.get("type") == "log":
            self.log(str(message.get("message", "")), str(message.get("level", "INFO")))

    # ============================================================
    # 热键注册
    # ============================================================
    def register_hotkeys(self) -> None:
        """按当前配置注册全部热键；重复调用先清理旧热键。

        功能热键（战斗/整理/石碑/地图/F3/F4）与模块/子页无关，POE2 前台即生效，
        战斗宏作用于当前激活的配置页（active_profile 跟随配置/旋风子页切换）；
        页面级动作键归属各自页面：F5 标定（旋风/坐标/开发）、F2 记录（测试），
        功能热键与当前页动作键同键时动作键优先；F12 急停全局。
        """
        s = self.settings
        combat_key = s.combat.hotkey
        sort_key = s.general.sort.hotkey
        tablet_key = s.general.tablet.hotkey
        map_key = s.general.map_click.hotkey
        market_key = s.market_scan.hotkey
        self.hotkeys.register_when_poe_active(
            "combat", combat_key, self.combat.toggle, self._function_guard(combat_key)
        )
        self.hotkeys.register_when_poe_active(
            "bag", sort_key, self.bag.toggle, self._function_guard(sort_key)
        )
        self.hotkeys.register_when_poe_active(
            "waystone", tablet_key, self.waystone.toggle, self._function_guard(tablet_key)
        )
        self.hotkeys.register_when_poe_active(
            "map", map_key, self.map_runner.toggle, self._function_guard(map_key)
        )
        # 市场抓取：热键线程转主线程触发交易页抓取（读取输入框需在主线程）
        self.hotkeys.register_when_poe_active(
            "market_scan", market_key, self._market_scan_trigger,
            self._function_guard(market_key),
        )
        # 默认/指定通货批量抓取：同为功能热键，POE2 前台即生效
        market_default_key = s.market_scan.hotkey_default
        market_custom_key = s.market_scan.hotkey_custom
        self.hotkeys.register_when_poe_active(
            "market_scan_default", market_default_key, self._market_scan_default_trigger,
            self._function_guard(market_default_key),
        )
        self.hotkeys.register_when_poe_active(
            "market_scan_custom", market_custom_key, self._market_scan_custom_trigger,
            self._function_guard(market_custom_key),
        )
        self.hotkeys.register_when_poe_active(
            "cal_first", CALIBRATE_KEY_FIRST, self.bag.calibrate_first,
            self._function_guard(CALIBRATE_KEY_FIRST),
        )
        self.hotkeys.register_when_poe_active(
            "cal_second", CALIBRATE_KEY_SECOND, self.bag.calibrate_second,
            self._function_guard(CALIBRATE_KEY_SECOND),
        )
        self._register_scoped(
            "cal_record", CALIBRATE_KEY_RECORD, self._record_pending_calibration,
            ("cyclone", "coords", "dev"), "F5 标定仅在「旋风/坐标/开发」页生效",
        )
        self._register_scoped(
            "recorder", RECORDER_KEY, self.recorder.toggle, ("test",),
            "F2 记录仅在「测试」页生效",
        )
        self.hotkeys.register("emergency", EMERGENCY_HOTKEY, self.emergency_stop)

    # ============================================================
    # 标定流程（货币 + 刷图 Q6 + 开发测量）
    # ============================================================
    @staticmethod
    def _calib_name(target: str) -> str:
        """待标定目标的中文名（如 currency:alch -> 点金石）。"""
        kind, key = target.split(":", 1)
        if kind == "currency":
            return CURRENCY_NAMES.get(key, key)
        if kind == "measure":
            # key 形如 point1 / range1
            prefix, index = key[:5], key[5:]
            return f"开发 {'点' if prefix == 'point' else '范围'}{index}"
        return "刷图 Q=6 数字"

    def toggle_calibration(self, target: str) -> None:
        """「标定」按钮：进入/取消待标定状态，等待游戏内按 F5。"""
        if self.pending_calib == target:
            self.pending_calib = None
            if target == "mapping:q6" and self._q6_marker is not None:
                self._q6_marker.cancel()
            if target.startswith("measure:range") and self._range_marker is not None:
                self._range_marker.cancel()
            self.log(f"已取消标定「{self._calib_name(target)}」")
        else:
            self.pending_calib = target
            if target == "mapping:q6":
                self.log(
                    f"标定「刷图 Q=6 数字」：请切换到游戏，将 Q 充满至显示 6 后按 "
                    f"{CALIBRATE_KEY_RECORD.upper()} 进入标记，"
                    f"然后右键点击检测数字的左上角，再右键点击右下角；再次点击按钮取消"
                )
            elif target.startswith("measure:range"):
                self._begin_range_mark()
            else:
                self.log(
                    f"标定「{self._calib_name(target)}」：请切换到游戏，"
                    f"将鼠标指向目标后按 {CALIBRATE_KEY_RECORD.upper()} 记录；再次点击按钮取消"
                )
        self._refresh_calib_buttons()

    def _begin_range_mark(self) -> None:
        """开启/重启左键框选会话（开发页「框选」按钮或标记中按 F5）。"""
        if self._range_marker is None:
            self._range_marker = RangeMarkSession(on_log=self.log, on_done=self._on_range_marked)
        self._range_marker.cancel()
        self._range_marker.begin()
        self.log(
            f"已开启框选「{self._calib_name(self.pending_calib or '')}」："
            f"请切换到游戏，按住鼠标左键拖出矩形后松开；标记中按 "
            f"{CALIBRATE_KEY_RECORD.upper()} 重新开始，再次点击按钮取消"
        )

    def _record_pending_calibration(self) -> None:
        """F5 回调（键盘线程，POE2 前台时触发）：记录货币/测量点 / 进入标记模式。"""
        target = self.pending_calib
        if target is None:
            self.log(
                f"当前没有待标定项：请在「旋风」「坐标」或「开发」页点击「标定/测量/框选」后再按 "
                f"{CALIBRATE_KEY_RECORD.upper()}"
            )
            return
        kind, key = target.split(":", 1)
        if kind == "mapping":
            # 刷图 Q=6：F5 进入右键两角标记模式（标记中再按 F5 = 重新开始）
            if self._q6_marker is None:
                self._q6_marker = Q6MarkSession(on_log=self.log, on_done=self._on_q6_marked)
            self._q6_marker.cancel()
            self._q6_marker.begin()
            self.log("已进入 Q6 标记模式：右键点击检测数字的左上角，再右键点击右下角")
            return
        if kind == "measure" and key.startswith("range"):
            self._begin_range_mark()  # 框选标记中按 F5 = 重新开始
            return
        pos = window.cursor_client_pos()
        if pos is None:
            self.log("标定失败：未找到 POE2 窗口")
            return
        if kind == "measure":
            self.settings.dev.measure_points[int(key[len("point"):])] = pos
        else:
            self.settings.currency[key] = pos
        save_settings(self.settings)
        self.pending_calib = None
        self.log(f"已标定「{self._calib_name(target)}」({pos.x}, {pos.y})")
        self.root.after(0, self._refresh_after_calibration)

    def _on_q6_marked(self, p1: Point, p2: Point) -> None:
        """Q6 第二次右键回调（鼠标钩子线程）：转主线程完成标定。"""
        self.root.after(0, lambda: self._finish_q6_mark(p1, p2))

    def _finish_q6_mark(self, p1: Point, p2: Point) -> None:
        """两角标记完成：规范化 ROI → 截模板 → 写配置 → 热重载掩模。"""
        if self.pending_calib != "mapping:q6":
            return  # 标记期间已被取消
        try:
            roi = normalize_roi(p1, p2, window.client_size())
            capture_template(roi)
        except CalibrateError as exc:
            self.log(f"标定失败：{exc}")
            return
        self.settings.combat.q6_roi = roi
        save_settings(self.settings)
        self.pending_calib = None
        self.log(
            f"已标定「刷图 Q=6 数字」区域 ({roi[0]}, {roi[1]}) - ({roi[2]}, {roi[3]})"
            f"（模板 templates/q6.png）"
        )
        self.mapping.reload_q6()  # 热重载掩模，运行中立即生效
        self.combat_module.refresh_mapping_roi(self.settings)
        self._refresh_calib_buttons()

    def _on_range_marked(self, p1: Point, p2: Point) -> None:
        """框选左键抬起回调（鼠标钩子线程）：转主线程完成测量。"""
        self.root.after(0, lambda: self._finish_range_mark(p1, p2))

    def _finish_range_mark(self, p1: Point, p2: Point) -> None:
        """框选完成：规范化范围 → 写配置 → 刷新显示。"""
        target = self.pending_calib
        if target is None or not target.startswith("measure:range"):
            return  # 框选期间已被取消
        try:
            rect = normalize_range(p1, p2, window.client_size())
        except MeasureError as exc:
            self.log(f"框选失败：{exc}")
            return
        index = int(target.split(":", 1)[1][len("range"):])
        self.settings.dev.measure_ranges[index] = rect
        save_settings(self.settings)
        self.pending_calib = None
        self.log(
            f"已框选「{self._calib_name(target)}」({rect[0]}, {rect[1]}) - ({rect[2]}, {rect[3]})"
            f"（{rect[2] - rect[0]}×{rect[3] - rect[1]}）"
        )
        self._refresh_after_calibration()

    def _refresh_after_calibration(self) -> None:
        """标定完成后刷新坐标显示与按钮状态（主线程）。"""
        self.dev_module.refresh_coords(self.settings)
        self.dev_module.refresh(self.settings)
        self._refresh_calib_buttons()

    def _refresh_calib_buttons(self) -> None:
        """根据待标定状态刷新各页的「标定/取消」按钮文案。"""
        self.combat_module.set_pending(self.pending_calib)
        self.dev_module.set_pending(self.pending_calib)

    def _on_bag_calibrated(self) -> None:
        """背包 F4 标定成功回调（键盘线程）：刷新格子间距显示。"""
        self.root.after(
            0, lambda: self.general_module.set_cell_size(self.settings.general.sort.cell_size)
        )

    # ============================================================
    # 刷图自动化（三线程 + FSM，控制并入旋风页）
    # ============================================================
    def _mapping_start(self) -> None:
        """「启动」按钮：POE2 前台时立即启动；否则等待切回游戏后自动启动。

        点按钮时焦点在工具窗口，必然非 POE2 前台，直接 start() 必失败；
        因此失败后进入待启动轮询，检测到 POE2 前台即自动启动。
        """
        self._mapping_start_gen += 1  # 作废旧轮询
        if self.mapping.running or self.mapping.start():
            return
        if window.is_poe_active():
            return  # 前台仍失败（如 dxcam 初始化失败），start() 内部已记录原因
        self.log("刷图助手待启动：请切回 POE2 窗口，检测到前台后自动启动（15 秒内有效）")
        self._mapping_start_poll(self._mapping_start_gen, 0)

    def _mapping_start_poll(self, gen: int, waited_ms: int) -> None:
        """待启动轮询：POE2 前台即启动；换代/已运行/超时即终止。"""
        if gen != self._mapping_start_gen or self.mapping.running:
            return
        if waited_ms >= MAPPING_START_TIMEOUT_MS:
            self.log("等待 POE2 前台超时，刷图助手未启动：请重新点「启动」")
            return
        if window.is_poe_active():
            self.mapping.start()
            return
        self.root.after(
            MAPPING_START_POLL_MS,
            lambda: self._mapping_start_poll(gen, waited_ms + MAPPING_START_POLL_MS),
        )

    def _mapping_stop(self) -> None:
        """「停止」按钮：停止刷图助手并清空模拟输入；同时取消待启动轮询。"""
        self._mapping_start_gen += 1
        self.mapping.stop(source="界面按钮")

    def _market_scan_trigger(self) -> None:
        """市场抓取热键回调（键盘线程）：转主线程触发交易页抓取。"""
        self.root.after(0, self.trade_module.trigger_test)

    def _market_scan_default_trigger(self) -> None:
        """默认通货批量抓取热键回调（键盘线程）：转主线程触发。"""
        self.root.after(0, self.trade_module.trigger_default)

    def _market_scan_custom_trigger(self) -> None:
        """指定通货批量抓取热键回调（键盘线程）：转主线程触发。"""
        self.root.after(0, self.trade_module.trigger_custom)

    # ============================================================
    # 状态轮询
    # ============================================================
    def _profile_name(self) -> str:
        if self.settings.combat.active_profile == CYCLONE_PROFILE:
            return "旋风"
        return f"配置{self.settings.combat.active_profile}"

    def _poll_status(self) -> None:
        """定时刷新状态区与各模块显示。"""
        self.poe_var.set("是" if window.is_poe_active() else "否")
        self.combat_var.set("运行" if self.combat.active else "停止")
        self.bag_var.set("整理中" if self.bag.running else "空闲")
        self.way_var.set("速点中" if self.waystone.running else "空闲")
        self.map_var.set("速点中" if self.map_runner.running else "空闲")
        self.profile_var.set(self._profile_name())
        self.general_module.set_cell_size(self.settings.general.sort.cell_size)
        self.combat_module.refresh_mapping_roi(self.settings)
        self.dev_module.refresh_coords(self.settings)
        self.combat_module.set_mapping_status(self.mapping.status())
        self.dev_module.set_status(self.recorder.status())
        self.dev_module.refresh(self.settings)
        self.root.after(STATUS_POLL_MS, self._poll_status)

    # ============================================================
    # 动作
    # ============================================================
    def save_config(self) -> None:
        """「保存配置」：同步控件值（含校验夹取）→ 写盘 → 重注册热键 → 应用日志过滤。"""
        self.sync_controls()
        save_settings(self.settings)
        self.load_controls()  # 回显夹取后的值
        self.register_hotkeys()
        self.log_panel.set_filter(self.settings.dev.log_level, self.settings.dev.debug)
        self.log("配置已保存，热键已生效")

    def emergency_stop(self) -> None:
        """F12：中断全部任务并释放所有按键。"""
        if self._q6_marker is not None:
            self._q6_marker.cancel()
        if self._range_marker is not None:
            self._range_marker.cancel()
        self.bag.request_stop()
        self.waystone.request_stop()
        self.map_runner.request_stop()
        self.combat.stop()
        self.mapping.stop(source="F12 急停")
        self.recorder.stop()
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
