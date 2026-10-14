#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置模型与 ini 读写（UTF-8）。

集中定义桌面工具的全部配置，按功能分组为嵌套模型：
- combat（[Combat]/[Profile1]）：战斗宏热键、激活配置、普通配置页按键策略
- general.sort（[Sort]）：背包整理热键、网格行列、格距与批量间隔
- general.tablet（[Tablet]）：石碑速点热键、货币、级别与批量间隔
- general.map_click（[Map]）：地图速点热键与批量间隔
- general.map_vaal（[MapVaal]）：瓦地图热键、批量间隔与目标地图阶级
- stash_ui（[StashUI]）：仓库界面布局（通货/Map 标签、阶级按钮、仓库页、地图格子）
- dev（[Dev]/[Measure]）：调试开关、日志级别、开发页测量坐标与框选范围
- market_scan（[MarketScan]）：通货市场抓取各阶段延时（坐标复用 [Measure] 槽位）
- currency（[Currency]）：货币坐标

读写通过 configparser，编码固定 UTF-8；坐标均为 POE2 客户区坐标
（与 AHK 版约定一致）。读取向后兼容旧段名（[General]/[Waystone]/[Bag]），
保存只写新段名，首次保存后旧段自然消失。
"""

from __future__ import annotations

import configparser
from dataclasses import dataclass, field
from pathlib import Path

# 配置文件位于项目根目录（本文件在 poe2_tools/config/ 内，需向上两级）
INI_PATH = Path(__file__).resolve().parent.parent.parent / "poe2_tools.ini"

# POE2 窗口标题关键字
POE_WINDOW_TITLE = "Path of Exile 2"

# ============================================================
# 常量（与 AHK 版规约一致）
# ============================================================
PROFILE_COUNT = 1

# 普通战斗配置页按键（内部标识沿用 AHK 命名，界面显示名见 ui 层）
SKILL_KEYS = ["LButton", "RButton", "Space", "q", "w", "e", "r", "t"]

MODE_DISABLED = "disabled"
MODE_SPAM = "spam"
MODE_HOLD = "hold"
MODES = (MODE_DISABLED, MODE_SPAM, MODE_HOLD)

MIN_INTERVAL_MS = 50
DEF_INTERVAL_MS = 300

# 批量操作统一约定：间隔可配置（5-5000ms）+ ±30% 随机抖动
BATCH_JITTER = 0.3
MIN_BATCH_INTERVAL_MS = 5
MAX_BATCH_INTERVAL_MS = 5000
DEF_DUMP_INTERVAL_MS = 30
DEF_WAY_INTERVAL_MS = 100
DEF_MAP_INTERVAL_MS = 100

# 货币：蜕变/增幅/富豪/崇高/混沌分三级，二级 = 一级 +64px，三级 = +128px（向右，1600×1024 实测）
CURRENCY_KEYS = ["trans", "aug", "regal", "ex", "chaos", "alch", "vaal", "whet", "scrap", "etch"]
CURRENCY_NAMES = {
    "trans": "蜕变", "aug": "增幅", "regal": "富豪", "ex": "崇高", "chaos": "混沌",
    "alch": "点金石", "vaal": "瓦尔", "whet": "磨刀石", "scrap": "护甲片", "etch": "奥术师",
}
TIERED_KEYS = ["trans", "aug", "regal", "ex", "chaos"]
TIER_SPACING = 64

# 地图速点固定流程：[[货币, 每格点击次数], ...]，完成后触发一次背包整理
# 点金石固定出 4 词，崇高×2 补满 6 词后瓦尔（原崇高×4 会多出 2 次无效点击）
MAP_PHASES = [["alch", 1], ["ex", 2], ["vaal", 1]]
# 瓦尔腐化有动画：最小间隔兜底（毫秒），避免漏点
MAP_MIN_INTERVAL_MS = {"vaal": 500}

DEFAULT_ROWS = 5
DEFAULT_COLS = 11

# 开发页测量槽位：6 个测量坐标 + 6 个框选范围（开发阶段收集信息用）
MEASURE_POINT_COUNT = 6
MEASURE_RANGE_COUNT = 6

# 通货市场抓取延时默认值（毫秒）：点击间隔 / 搜索下拉加载 / 市场面板刷新 /
# 选中搜索结果后等待选中生效（偏保守：避免界面未刷新导致选错通货或截到旧结果）
DEF_CLICK_DELAY_MS = 300
DEF_SEARCH_LOAD_DELAY_MS = 1200
DEF_UI_REFRESH_DELAY_MS = 800
DEF_SELECT_DELAY_MS = 500

# 日志级别白名单（非法值回退 INFO）
LOG_LEVELS = ("DEBUG", "INFO", "WARN", "ERROR")

# 紧急停止热键（固定，不可修改）
EMERGENCY_HOTKEY = "f12"


# ============================================================
# 数据模型
# ============================================================
@dataclass
class Point:
    """客户区坐标点。"""

    x: int
    y: int


@dataclass
class KeyConfig:
    """单个按键的战斗配置。jitter_ms 为毫秒级随机附加（间隔 + 0~jitter_ms）。"""

    mode: str = MODE_DISABLED
    interval_ms: int = DEF_INTERVAL_MS
    jitter_ms: int = 0


@dataclass
class CombatSettings:
    """战斗分组：战斗宏热键、激活配置页、普通配置页按键策略。"""

    hotkey: str = "f2"
    active_profile: int = 1  # 夹取 1~PROFILE_COUNT
    profiles: list[dict[str, KeyConfig]] = field(default_factory=list)  # [Profile1]

    def __post_init__(self) -> None:
        # profiles 为空时填默认值（含默认键位策略）
        if not self.profiles:
            self.profiles = default_profiles()


@dataclass
class SortSettings:
    """背包整理分组（[Sort]）。"""

    hotkey: str = "f1"
    rows: int = DEFAULT_ROWS
    cols: int = DEFAULT_COLS
    interval_ms: int = DEF_DUMP_INTERVAL_MS
    cell_size: int = 0


@dataclass
class TabletSettings:
    """石碑速点分组（[Tablet]）。"""

    hotkey: str = "f6"
    currency: str = "alch"
    tier: int = 1
    interval_ms: int = DEF_WAY_INTERVAL_MS


@dataclass
class MapClickSettings:
    """地图速点分组（[Map]）。"""

    hotkey: str = "f7"
    interval_ms: int = DEF_MAP_INTERVAL_MS


@dataclass
class MapVaalSettings:
    """瓦地图分组（[MapVaal]）：仓库 Map 页批量取未满 6 词未污染图 →
    背包内点金/崇高至 6 词 → 瓦前检查补满 → 盲点瓦尔 → 按阶级/数值/词缀分流存回。"""

    hotkey: str = "ctrl+f7"
    interval_ms: int = DEF_MAP_INTERVAL_MS
    tier: int = 15  # 目标地图阶级（1~16）
    # 瓦后分流阈值：物品稀有度+怪物效能 ≥ 该值存入「100 地图」仓
    value_threshold: int = 100


@dataclass
class StashUISettings:
    """仓库界面布局（[StashUI]）。

    默认值为 2026-10-13 当前布局实测坐标（与 poe2_tools.ini 一致）；
    分辨率/窗口布局变化时直接改 ini。注意标签列表纵坐标随选中页变化，
    tab_* 均以「Map 页选中」状态实测为准（与存回阶段点击时状态一致）。
    tier_cols/tier_rows：地图阶级按钮各列 x 与两行 y（I-VIII / IX-XVI）。
    page_*：仓库页绿色按钮（第 1 页 x、间距、y、页数）。
    stash_grid_*：地图仓库格子（第 1 格中心、格距、行列数）。
    tab_map100：「100 地图」仓（高级地图仓下一行，瓦后数值分流用）。
    """

    tab_currency: Point = field(default_factory=lambda: Point(695, 108))
    tab_map: Point = field(default_factory=lambda: Point(695, 135))
    tab_advanced_map: Point = field(default_factory=lambda: Point(695, 590))
    tab_map100: Point = field(default_factory=lambda: Point(695, 616))
    tier_cols: list[int] = field(
        default_factory=lambda: [82, 149, 216, 282, 349, 416, 482, 549]
    )
    tier_rows: list[int] = field(default_factory=lambda: [171, 233])
    page_x0: int = 175
    page_pitch: int = 57
    page_y: int = 304
    page_count: int = 6
    stash_grid_origin: Point = field(default_factory=lambda: Point(63, 347))
    stash_grid_cell: int = 46
    stash_grid_rows: int = 8
    stash_grid_cols: int = 12


@dataclass
class GeneralSettings:
    """通用功能分组：背包整理 + 石碑速点 + 地图速点 + 瓦地图。"""

    sort: SortSettings = field(default_factory=SortSettings)
    tablet: TabletSettings = field(default_factory=TabletSettings)
    map_click: MapClickSettings = field(default_factory=MapClickSettings)
    map_vaal: MapVaalSettings = field(default_factory=MapVaalSettings)


@dataclass
class DevSettings:
    """开发分组（[Dev] + [Measure]）：调试开关、日志级别、测量数据。"""

    debug: bool = False
    log_level: str = "INFO"  # DEBUG/INFO/WARN/ERROR，非法回退 INFO
    # 开发页测量数据：槽位号（1 起）→ 客户区坐标点 / 范围 (x1,y1,x2,y2)
    measure_points: dict[int, Point] = field(default_factory=dict)
    measure_ranges: dict[int, tuple[int, int, int, int]] = field(default_factory=dict)


@dataclass
class MarketScanSettings:
    """通货市场抓取分组（[MarketScan]）：各阶段延时（毫秒）。

    坐标复用开发页测量槽位（[Measure]）：point1~5 = 我需要的/我拥有的/搜索框/
    市场比率按键/搜索结果首项，range3 = 交易比例与库存结果面板。
    """

    click_delay_ms: int = DEF_CLICK_DELAY_MS
    search_load_delay_ms: int = DEF_SEARCH_LOAD_DELAY_MS
    ui_refresh_delay_ms: int = DEF_UI_REFRESH_DELAY_MS
    select_delay_ms: int = DEF_SELECT_DELAY_MS  # 选中搜索结果后的等待
    hotkey: str = "f8"  # 比例测试启动热键（POE2 前台生效，游戏内手动触发抓取）
    # 默认/指定通货批量抓取（交易模块子页）
    hotkey_default: str = "f9"  # 默认通货（崇高/混沌/神圣）抓取热键
    hotkey_custom: str = "f10"  # 指定通货抓取热键
    custom_currency: str = ""  # 指定通货游戏内英文全名
    # 自动套利批量抓取（交易模块「自动」子页）
    hotkey_auto: str = "f11"  # 自动套利抓取热键
    auto_range_lo: float = 0.5  # 候选通货神圣价值下限
    auto_range_hi: float = 20.0  # 候选通货神圣价值上限
    # 结果面板截图偏移（修正框选偏差：实测需左移 10、下移 20）
    range_offset_x: int = -10
    range_offset_y: int = 20
    # 交易页测试抓取的通货对（游戏内英文全名）
    currency_a: str = "Divine Orb"
    currency_b: str = "Chaos Orb"


@dataclass
class Settings:
    """桌面工具全部配置（分组模型）。"""

    combat: CombatSettings = field(default_factory=CombatSettings)
    general: GeneralSettings = field(default_factory=GeneralSettings)
    dev: DevSettings = field(default_factory=DevSettings)
    market_scan: MarketScanSettings = field(default_factory=MarketScanSettings)
    stash_ui: StashUISettings = field(default_factory=StashUISettings)  # [StashUI]
    currency: dict[str, Point] = field(default_factory=dict)  # [Currency]


def default_key_config(key: str) -> KeyConfig:
    """按键默认配置：鼠标左键连点 100ms，其余禁用；抖动默认 15ms。"""
    if key == "LButton":
        return KeyConfig(MODE_SPAM, 100, 15)
    return KeyConfig(MODE_DISABLED, DEF_INTERVAL_MS, 15)


def default_profiles() -> list[dict[str, KeyConfig]]:
    """普通战斗配置页的默认配置。"""
    return [{key: default_key_config(key) for key in SKILL_KEYS} for _ in range(PROFILE_COUNT)]


# ============================================================
# 读取辅助
# ============================================================
def _to_int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _to_float(value: str, default: float) -> float:
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _read_value(
    config: configparser.ConfigParser,
    section: str,
    key: str,
    legacy: tuple[str, str] | None = None,
) -> str:
    """读取配置值（去空白）：新段新键优先，为空时回退旧段旧键。"""
    raw = config.get(section, key, fallback="").strip()
    if not raw and legacy is not None:
        raw = config.get(legacy[0], legacy[1], fallback="").strip()
    return raw


def _read_mode(config: configparser.ConfigParser, section: str, key: str, default: str) -> str:
    mode = config.get(section, key, fallback=default).strip()
    return mode if mode in MODES else default


def _read_key_config(
    config: configparser.ConfigParser, section: str, key: str, default: KeyConfig
) -> KeyConfig:
    mode = _read_mode(config, section, f"{key}_mode", default.mode)
    interval = _to_int(config.get(section, f"{key}_interval", fallback=str(default.interval_ms)),
                       default.interval_ms)
    # 抖动毫秒数（间隔 + 0~jitter_ms）；兼容旧版布尔键 _random（1 → 间隔的 15%）
    jitter_raw = config.get(section, f"{key}_jitter", fallback="").strip()
    if jitter_raw:
        jitter = _clamp(_to_int(jitter_raw, default.jitter_ms), 0, MAX_BATCH_INTERVAL_MS)
    else:
        legacy_random = _to_int(config.get(section, f"{key}_random", fallback=""), -1)
        jitter = round(interval * 0.15) if legacy_random == 1 else (
            0 if legacy_random == 0 else default.jitter_ms
        )
    return KeyConfig(mode, max(MIN_INTERVAL_MS, interval), jitter)


def _read_point(config: configparser.ConfigParser, section: str, key: str) -> Point | None:
    x = config.get(section, f"{key}_x", fallback="").strip()
    y = config.get(section, f"{key}_y", fallback="").strip()
    if not x or not y:
        return None
    return Point(_to_int(x, 0), _to_int(y, 0))


def _read_range(config: configparser.ConfigParser, section: str, key: str) -> tuple[int, int, int, int] | None:
    """读取 "x1,y1,x2,y2" 形式的范围；缺段或非法（非四点/x2<=x1/y2<=y1）返回 None。"""
    raw = config.get(section, key, fallback="").strip()
    if not raw:
        return None
    parts = [_to_int(p, 0) for p in raw.split(",")]
    if len(parts) != 4 or parts[2] <= parts[0] or parts[3] <= parts[1]:
        return None
    return (parts[0], parts[1], parts[2], parts[3])


def _read_int_list(config: configparser.ConfigParser, section: str, key: str) -> list[int]:
    """读取逗号分隔的整数列表（如 "115,210,305"）；缺失返回空列表。"""
    raw = config.get(section, key, fallback="").strip()
    if not raw:
        return []
    return [_to_int(p, 0) for p in raw.split(",") if p.strip()]


# ============================================================
# 加载 / 保存
# ============================================================
def load_settings(path: Path | None = None) -> Settings:
    """
    从 ini 加载配置；文件缺失或字段非法时使用默认值。

    向后兼容：新段（[Combat]/[Sort]/[Tablet]）的键为空时回退读旧段旧键
    （[General] CombatHotkey/DumpHotkey/ActiveProfile、[Bag]、[Waystone]），
    其余段（[Map]/[Profile1]/[Currency]/[Measure]）段名不变。
    旧 [Cyclone] 段（鼠标三键策略）与旧 [Mapping] 段（刷图 Q6 ROI）已随
    旋风重构废弃，读取时忽略，保存时自然消失。
    """
    ini = path or INI_PATH
    config = configparser.ConfigParser()
    config.optionxform = str
    if ini.exists():
        with open(ini, "r", encoding="utf-8") as f:
            config.read_file(f)

    s = Settings()

    # 战斗分组：[Combat] ← 旧 [General] CombatHotkey/ActiveProfile
    s.combat.hotkey = _read_value(config, "Combat", "Hotkey", ("General", "CombatHotkey")) or "f2"
    s.combat.active_profile = _clamp(
        _to_int(_read_value(config, "Combat", "ActiveProfile", ("General", "ActiveProfile")), 1),
        1, PROFILE_COUNT,
    )

    # 背包整理分组：[Sort] ← 旧 [General] DumpHotkey、旧 [Bag]
    sort = s.general.sort
    sort.hotkey = _read_value(config, "Sort", "Hotkey", ("General", "DumpHotkey")) or "f1"
    sort.rows = _clamp(_to_int(_read_value(config, "Sort", "Rows", ("Bag", "Rows")),
                               DEFAULT_ROWS), 1, 30)
    sort.cols = _clamp(_to_int(_read_value(config, "Sort", "Cols", ("Bag", "Cols")),
                               DEFAULT_COLS), 1, 30)
    sort.interval_ms = _clamp(
        _to_int(_read_value(config, "Sort", "Interval", ("Bag", "DumpInterval")),
                DEF_DUMP_INTERVAL_MS),
        MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
    )
    sort.cell_size = _to_int(_read_value(config, "Sort", "CellSize", ("Bag", "CellSize")), 0)

    # 石碑速点分组：[Tablet] ← 旧 [Waystone]
    tablet = s.general.tablet
    tablet.hotkey = _read_value(config, "Tablet", "Hotkey", ("Waystone", "Hotkey")) or "f6"
    tablet_currency = _read_value(config, "Tablet", "Currency", ("Waystone", "Currency")) or "alch"
    tablet.currency = tablet_currency if tablet_currency in CURRENCY_KEYS else "alch"
    tablet.tier = _clamp(_to_int(_read_value(config, "Tablet", "Tier", ("Waystone", "Tier")), 1), 1, 3)
    tablet.interval_ms = _clamp(
        _to_int(_read_value(config, "Tablet", "Interval", ("Waystone", "Interval")),
                DEF_WAY_INTERVAL_MS),
        MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
    )

    # 地图速点分组：[Map] 段名不变，直接读
    map_click = s.general.map_click
    map_click.hotkey = _read_value(config, "Map", "Hotkey") or "f7"
    map_click.interval_ms = _clamp(
        _to_int(_read_value(config, "Map", "Interval"), DEF_MAP_INTERVAL_MS),
        MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
    )

    # 瓦地图分组：[MapVaal]
    map_vaal = s.general.map_vaal
    map_vaal.hotkey = _read_value(config, "MapVaal", "Hotkey") or "ctrl+f7"
    map_vaal.interval_ms = _clamp(
        _to_int(_read_value(config, "MapVaal", "Interval"), DEF_MAP_INTERVAL_MS),
        MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
    )
    map_vaal.tier = _clamp(_to_int(_read_value(config, "MapVaal", "Tier"), 15), 1, 16)
    map_vaal.value_threshold = _clamp(
        _to_int(_read_value(config, "MapVaal", "ValueThreshold"), 100), 0, 1000
    )

    # 仓库界面布局：[StashUI]（缺失字段保留默认值）
    ui = s.stash_ui
    tab_currency = _read_point(config, "StashUI", "TabCurrency")
    if tab_currency is not None:
        ui.tab_currency = tab_currency
    tab_map = _read_point(config, "StashUI", "TabMap")
    if tab_map is not None:
        ui.tab_map = tab_map
    tab_advanced_map = _read_point(config, "StashUI", "TabAdvancedMap")
    if tab_advanced_map is not None:
        ui.tab_advanced_map = tab_advanced_map
    tab_map100 = _read_point(config, "StashUI", "TabMap100")
    if tab_map100 is not None:
        ui.tab_map100 = tab_map100
    tier_cols = _read_int_list(config, "StashUI", "TierCols")
    if len(tier_cols) == 8:
        ui.tier_cols = tier_cols
    tier_rows = _read_int_list(config, "StashUI", "TierRows")
    if len(tier_rows) == 2:
        ui.tier_rows = tier_rows
    ui.page_x0 = _to_int(_read_value(config, "StashUI", "PageX0"), ui.page_x0)
    ui.page_pitch = _to_int(_read_value(config, "StashUI", "PagePitch"), ui.page_pitch)
    ui.page_y = _to_int(_read_value(config, "StashUI", "PageY"), ui.page_y)
    ui.page_count = _clamp(
        _to_int(_read_value(config, "StashUI", "PageCount"), ui.page_count), 1, 20
    )
    grid_origin = _read_point(config, "StashUI", "GridOrigin")
    if grid_origin is not None:
        ui.stash_grid_origin = grid_origin
    ui.stash_grid_cell = _clamp(
        _to_int(_read_value(config, "StashUI", "GridCell"), ui.stash_grid_cell), 10, 200
    )
    ui.stash_grid_rows = _clamp(
        _to_int(_read_value(config, "StashUI", "GridRows"), ui.stash_grid_rows), 1, 30
    )
    ui.stash_grid_cols = _clamp(
        _to_int(_read_value(config, "StashUI", "GridCols"), ui.stash_grid_cols), 1, 30
    )

    # 货币坐标（段名不变，未标定槽位省略）
    for key in CURRENCY_KEYS:
        point = _read_point(config, "Currency", key)
        if point is not None:
            s.currency[key] = point

    # 普通战斗配置页按键策略（段名不变）
    for i in range(PROFILE_COUNT):
        section = f"Profile{i + 1}"
        profile: dict[str, KeyConfig] = {}
        for key in SKILL_KEYS:
            profile[key] = _read_key_config(config, section, key, default_key_config(key))
        s.combat.profiles[i] = profile

    # 开发分组：[Dev] 调试开关与日志级别
    s.dev.debug = config.get("Dev", "Debug", fallback="0").strip() in ("1", "true", "yes")
    log_level = config.get("Dev", "LogLevel", fallback="INFO").strip().upper()
    s.dev.log_level = log_level if log_level in LOG_LEVELS else "INFO"

    # 开发页测量数据（段名不变）
    for i in range(1, MEASURE_POINT_COUNT + 1):
        point = _read_point(config, "Measure", f"point{i}")
        if point is not None:
            s.dev.measure_points[i] = point
    for i in range(1, MEASURE_RANGE_COUNT + 1):
        rect = _read_range(config, "Measure", f"range{i}")
        if rect is not None:
            s.dev.measure_ranges[i] = rect

    # 通货市场抓取延时（[MarketScan]，夹取 0~60000ms）
    ms = s.market_scan
    ms.click_delay_ms = _clamp(
        _to_int(config.get("MarketScan", "ClickDelay", fallback=str(DEF_CLICK_DELAY_MS)),
                DEF_CLICK_DELAY_MS), 0, 60000)
    ms.search_load_delay_ms = _clamp(
        _to_int(config.get("MarketScan", "SearchLoadDelay", fallback=str(DEF_SEARCH_LOAD_DELAY_MS)),
                DEF_SEARCH_LOAD_DELAY_MS), 0, 60000)
    ms.ui_refresh_delay_ms = _clamp(
        _to_int(config.get("MarketScan", "UiRefreshDelay", fallback=str(DEF_UI_REFRESH_DELAY_MS)),
                DEF_UI_REFRESH_DELAY_MS), 0, 60000)
    ms.select_delay_ms = _clamp(
        _to_int(config.get("MarketScan", "SelectDelay", fallback=str(DEF_SELECT_DELAY_MS)),
                DEF_SELECT_DELAY_MS), 0, 60000)
    ms.currency_a = config.get("MarketScan", "CurrencyA", fallback="Divine Orb").strip() or "Divine Orb"
    ms.currency_b = config.get("MarketScan", "CurrencyB", fallback="Chaos Orb").strip() or "Chaos Orb"
    ms.hotkey = config.get("MarketScan", "Hotkey", fallback="f8").strip().lower() or "f8"
    ms.hotkey_default = (
        config.get("MarketScan", "HotkeyDefault", fallback="f9").strip().lower() or "f9"
    )
    ms.hotkey_custom = (
        config.get("MarketScan", "HotkeyCustom", fallback="f10").strip().lower() or "f10"
    )
    ms.custom_currency = config.get("MarketScan", "CustomCurrency", fallback="").strip()
    ms.hotkey_auto = (
        config.get("MarketScan", "HotkeyAuto", fallback="f11").strip().lower() or "f11"
    )
    ms.auto_range_lo = _clamp(
        _to_float(config.get("MarketScan", "AutoRangeLo", fallback="0.5"), 0.5), 0.0, 100000.0)
    ms.auto_range_hi = _clamp(
        _to_float(config.get("MarketScan", "AutoRangeHi", fallback="20"), 20.0), 0.0, 100000.0)
    ms.range_offset_x = _clamp(
        _to_int(config.get("MarketScan", "RangeOffsetX", fallback="-10"), -10), -500, 500)
    ms.range_offset_y = _clamp(
        _to_int(config.get("MarketScan", "RangeOffsetY", fallback="20"), 20), -500, 500)
    return s


def save_settings(s: Settings, path: Path | None = None) -> None:
    """把配置写入 ini（UTF-8）。只写新段名，全量重写（未标定槽位省略）。"""
    ini = path or INI_PATH
    config = configparser.ConfigParser()
    config.optionxform = str

    config["Combat"] = {
        "Hotkey": s.combat.hotkey,
        "ActiveProfile": str(s.combat.active_profile),
    }
    sort = s.general.sort
    config["Sort"] = {
        "Hotkey": sort.hotkey,
        "Rows": str(sort.rows),
        "Cols": str(sort.cols),
        "Interval": str(sort.interval_ms),
        "CellSize": str(sort.cell_size),
    }
    tablet = s.general.tablet
    config["Tablet"] = {
        "Hotkey": tablet.hotkey,
        "Currency": tablet.currency,
        "Tier": str(tablet.tier),
        "Interval": str(tablet.interval_ms),
    }
    map_click = s.general.map_click
    config["Map"] = {"Hotkey": map_click.hotkey, "Interval": str(map_click.interval_ms)}

    map_vaal = s.general.map_vaal
    config["MapVaal"] = {
        "Hotkey": map_vaal.hotkey,
        "Interval": str(map_vaal.interval_ms),
        "Tier": str(map_vaal.tier),
        "ValueThreshold": str(map_vaal.value_threshold),
    }

    ui = s.stash_ui
    config["StashUI"] = {
        "TabCurrency_x": str(ui.tab_currency.x),
        "TabCurrency_y": str(ui.tab_currency.y),
        "TabMap_x": str(ui.tab_map.x),
        "TabMap_y": str(ui.tab_map.y),
        "TabAdvancedMap_x": str(ui.tab_advanced_map.x),
        "TabAdvancedMap_y": str(ui.tab_advanced_map.y),
        "TabMap100_x": str(ui.tab_map100.x),
        "TabMap100_y": str(ui.tab_map100.y),
        "TierCols": ",".join(str(v) for v in ui.tier_cols),
        "TierRows": ",".join(str(v) for v in ui.tier_rows),
        "PageX0": str(ui.page_x0),
        "PagePitch": str(ui.page_pitch),
        "PageY": str(ui.page_y),
        "PageCount": str(ui.page_count),
        "GridOrigin_x": str(ui.stash_grid_origin.x),
        "GridOrigin_y": str(ui.stash_grid_origin.y),
        "GridCell": str(ui.stash_grid_cell),
        "GridRows": str(ui.stash_grid_rows),
        "GridCols": str(ui.stash_grid_cols),
    }

    currency_section: dict[str, str] = {}
    for key in CURRENCY_KEYS:
        if key in s.currency:
            p = s.currency[key]
            currency_section[f"{key}_x"] = str(p.x)
            currency_section[f"{key}_y"] = str(p.y)
    config["Currency"] = currency_section

    for i in range(PROFILE_COUNT):
        section: dict[str, str] = {}
        for key in SKILL_KEYS:
            c = s.combat.profiles[i].get(key, default_key_config(key))
            section[f"{key}_mode"] = c.mode
            section[f"{key}_interval"] = str(c.interval_ms)
            section[f"{key}_jitter"] = str(c.jitter_ms)
        config[f"Profile{i + 1}"] = section

    measure_section: dict[str, str] = {}
    for i, p in sorted(s.dev.measure_points.items()):
        measure_section[f"point{i}_x"] = str(p.x)
        measure_section[f"point{i}_y"] = str(p.y)
    for i, rect in sorted(s.dev.measure_ranges.items()):
        measure_section[f"range{i}"] = ",".join(str(v) for v in rect)
    config["Measure"] = measure_section

    config["Dev"] = {"Debug": "1" if s.dev.debug else "0", "LogLevel": s.dev.log_level}

    ms = s.market_scan
    config["MarketScan"] = {
        "ClickDelay": str(ms.click_delay_ms),
        "SearchLoadDelay": str(ms.search_load_delay_ms),
        "UiRefreshDelay": str(ms.ui_refresh_delay_ms),
        "SelectDelay": str(ms.select_delay_ms),
        "Hotkey": ms.hotkey,
        "HotkeyDefault": ms.hotkey_default,
        "HotkeyCustom": ms.hotkey_custom,
        "CustomCurrency": ms.custom_currency,
        "HotkeyAuto": ms.hotkey_auto,
        "AutoRangeLo": str(ms.auto_range_lo),
        "AutoRangeHi": str(ms.auto_range_hi),
        "RangeOffsetX": str(ms.range_offset_x),
        "RangeOffsetY": str(ms.range_offset_y),
        "CurrencyA": ms.currency_a,
        "CurrencyB": ms.currency_b,
    }

    ini.parent.mkdir(parents=True, exist_ok=True)
    with open(ini, "w", encoding="utf-8") as f:
        config.write(f)


# ============================================================
# 货币坐标推导
# ============================================================
def currency_coord(s: Settings, key: str, tier: int = 1) -> Point | None:
    """
    解析货币坐标：三级货币按级别向右偏移（二级 +64px，三级 +128px，1600×1024 实测）。
    未标定返回 None。
    """
    if key not in s.currency:
        return None
    base = s.currency[key]
    dx = (tier - 1) * TIER_SPACING if key in TIERED_KEYS else 0
    return Point(base.x + dx, base.y)
