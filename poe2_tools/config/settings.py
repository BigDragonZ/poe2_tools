#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
配置模型与 ini 读写（UTF-8）。

集中定义桌面工具的全部配置：热键、背包网格、石碑/地图速点、
货币坐标、战斗配置页（配置1-4）与旋风页。读写通过 configparser，
编码固定 UTF-8；坐标均为 POE2 客户区坐标（与 AHK 版约定一致）。
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
PROFILE_COUNT = 4
CYCLONE_PROFILE = 5  # 旋风配置页序号

# 普通战斗配置页按键（内部标识沿用 AHK 命名，界面显示名见 ui 层）
SKILL_KEYS = ["LButton", "RButton", "Space", "q", "w", "e", "r", "t"]
# 旋风页鼠标按键
CYC_KEYS = ["LButton", "MButton", "RButton"]
# 旋风 Q/E 数字检测键
CYC_DETECT_KEYS = ["q", "e"]

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
DEF_WAY_INTERVAL_MS = 50
DEF_MAP_INTERVAL_MS = 50

# 旋风 Q/E 数字检测
CYC_DETECT_MS = 2000      # 检测间隔
CYC_NUM_HW = 8            # 像素法检测区域半径（17×19）
CYC_NUM_HH = 9
CYC_TEMPLATE_RADIUS = 30  # 模板匹配搜索半径（标定点 ±30px）
CYC_MATCH_THRESHOLD = 0.9  # OpenCV 模板匹配阈值（≈ FindText 容错 10%）

# 货币：蜕变/增幅/富豪/崇高/混沌分三级，二级 = 一级 +70px，三级 = +140px（向右）
CURRENCY_KEYS = ["trans", "aug", "regal", "ex", "chaos", "alch", "vaal", "whet", "scrap", "etch"]
CURRENCY_NAMES = {
    "trans": "蜕变", "aug": "增幅", "regal": "富豪", "ex": "崇高", "chaos": "混沌",
    "alch": "点金石", "vaal": "瓦尔", "whet": "磨刀石", "scrap": "护甲片", "etch": "奥术师",
}
TIERED_KEYS = ["trans", "aug", "regal", "ex", "chaos"]
TIER_SPACING = 70

# 地图速点固定流程：[[货币, 每格点击次数], ...]，完成后触发一次背包整理
MAP_PHASES = [["alch", 1], ["ex", 4], ["vaal", 1]]

DEFAULT_ROWS = 5
DEFAULT_COLS = 11

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
    """单个按键的战斗配置。"""

    mode: str = MODE_DISABLED
    interval_ms: int = DEF_INTERVAL_MS
    random_jitter: bool = True


@dataclass
class Settings:
    """桌面工具全部配置。"""

    combat_hotkey: str = "f2"
    dump_hotkey: str = "f1"
    active_profile: int = 1
    way_hotkey: str = "f6"
    way_currency: str = "alch"
    way_tier: int = 1
    way_interval_ms: int = DEF_WAY_INTERVAL_MS
    map_hotkey: str = "f7"
    map_interval_ms: int = DEF_MAP_INTERVAL_MS
    cell_size: int = 0
    rows: int = DEFAULT_ROWS
    cols: int = DEFAULT_COLS
    dump_interval_ms: int = DEF_DUMP_INTERVAL_MS
    cyclone: dict[str, KeyConfig] = field(default_factory=dict)
    cyclone_coords: dict[str, Point] = field(default_factory=dict)
    currency: dict[str, Point] = field(default_factory=dict)
    profiles: list[dict[str, KeyConfig]] = field(default_factory=list)
    bridge_enabled: bool = False
    bridge_port: int = 8322

    def __post_init__(self) -> None:
        if not self.cyclone:
            self.cyclone = default_cyclone()
        if not self.profiles:
            self.profiles = default_profiles()


def default_key_config(key: str) -> KeyConfig:
    """按键默认配置：鼠标左键连点 100ms，其余禁用。"""
    if key == "LButton":
        return KeyConfig(MODE_SPAM, 100, True)
    return KeyConfig(MODE_DISABLED, DEF_INTERVAL_MS, True)


def default_cyclone() -> dict[str, KeyConfig]:
    """旋风页默认配置（鼠标三键）。"""
    return {key: default_key_config(key) for key in CYC_KEYS}


def default_profiles() -> list[dict[str, KeyConfig]]:
    """四个战斗配置页的默认配置。"""
    return [{key: default_key_config(key) for key in SKILL_KEYS} for _ in range(PROFILE_COUNT)]


# ============================================================
# 读取辅助
# ============================================================
def _to_int(value: str, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _clamp(value: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, value))


def _read_mode(config: configparser.ConfigParser, section: str, key: str, default: str) -> str:
    mode = config.get(section, key, fallback=default).strip()
    return mode if mode in MODES else default


def _read_key_config(
    config: configparser.ConfigParser, section: str, key: str, default: KeyConfig
) -> KeyConfig:
    mode = _read_mode(config, section, f"{key}_mode", default.mode)
    interval = _to_int(config.get(section, f"{key}_interval", fallback=str(default.interval_ms)),
                       default.interval_ms)
    rnd = _to_int(config.get(section, f"{key}_random", fallback="1"), 1)
    return KeyConfig(mode, max(MIN_INTERVAL_MS, interval), bool(rnd))


def _read_point(config: configparser.ConfigParser, section: str, key: str) -> Point | None:
    x = config.get(section, f"{key}_x", fallback="").strip()
    y = config.get(section, f"{key}_y", fallback="").strip()
    if not x or not y:
        return None
    return Point(_to_int(x, 0), _to_int(y, 0))


# ============================================================
# 加载 / 保存
# ============================================================
def load_settings(path: Path | None = None) -> Settings:
    """从 ini 加载配置；文件缺失或字段非法时使用默认值。"""
    ini = path or INI_PATH
    config = configparser.ConfigParser()
    config.optionxform = str
    if ini.exists():
        with open(ini, "r", encoding="utf-8") as f:
            config.read_file(f)

    s = Settings()
    s.combat_hotkey = config.get("General", "CombatHotkey", fallback=s.combat_hotkey).strip() or "f2"
    s.dump_hotkey = config.get("General", "DumpHotkey", fallback=s.dump_hotkey).strip() or "f1"
    s.active_profile = _clamp(
        _to_int(config.get("General", "ActiveProfile", fallback="1"), 1), 1, CYCLONE_PROFILE
    )
    s.way_hotkey = config.get("Waystone", "Hotkey", fallback=s.way_hotkey).strip() or "f6"
    way_currency = config.get("Waystone", "Currency", fallback=s.way_currency).strip()
    s.way_currency = way_currency if way_currency in CURRENCY_KEYS else "alch"
    s.way_tier = _clamp(_to_int(config.get("Waystone", "Tier", fallback="1"), 1), 1, 3)
    s.way_interval_ms = _clamp(
        _to_int(config.get("Waystone", "Interval", fallback=str(DEF_WAY_INTERVAL_MS)),
                DEF_WAY_INTERVAL_MS),
        MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
    )
    s.map_hotkey = config.get("Map", "Hotkey", fallback=s.map_hotkey).strip() or "f7"
    s.map_interval_ms = _clamp(
        _to_int(config.get("Map", "Interval", fallback=str(DEF_MAP_INTERVAL_MS)),
                DEF_MAP_INTERVAL_MS),
        MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
    )
    s.cell_size = _to_int(config.get("Bag", "CellSize", fallback="0"), 0)
    s.rows = _clamp(_to_int(config.get("Bag", "Rows", fallback=str(DEFAULT_ROWS)), DEFAULT_ROWS), 1, 30)
    s.cols = _clamp(_to_int(config.get("Bag", "Cols", fallback=str(DEFAULT_COLS)), DEFAULT_COLS), 1, 30)
    s.dump_interval_ms = _clamp(
        _to_int(config.get("Bag", "DumpInterval", fallback=str(DEF_DUMP_INTERVAL_MS)),
                DEF_DUMP_INTERVAL_MS),
        MIN_BATCH_INTERVAL_MS, MAX_BATCH_INTERVAL_MS,
    )

    for key in CYC_KEYS:
        s.cyclone[key] = _read_key_config(config, "Cyclone", key, default_key_config(key))
    for key in CYC_DETECT_KEYS:
        point = _read_point(config, "Cyclone", key)
        if point is not None:
            s.cyclone_coords[key] = point

    for key in CURRENCY_KEYS:
        point = _read_point(config, "Currency", key)
        if point is not None:
            s.currency[key] = point

    for i in range(PROFILE_COUNT):
        section = f"Profile{i + 1}"
        profile: dict[str, KeyConfig] = {}
        for key in SKILL_KEYS:
            profile[key] = _read_key_config(config, section, key, default_key_config(key))
        s.profiles[i] = profile

    s.bridge_enabled = config.get("Bridge", "Enabled", fallback="0").strip() in ("1", "true", "yes")
    s.bridge_port = _clamp(_to_int(config.get("Bridge", "Port", fallback="8322"), 8322), 1024, 65535)
    return s


def save_settings(s: Settings, path: Path | None = None) -> None:
    """把配置写入 ini（UTF-8）。"""
    ini = path or INI_PATH
    config = configparser.ConfigParser()
    config.optionxform = str

    config["General"] = {
        "CombatHotkey": s.combat_hotkey,
        "DumpHotkey": s.dump_hotkey,
        "ActiveProfile": str(s.active_profile),
    }
    config["Waystone"] = {
        "Hotkey": s.way_hotkey,
        "Currency": s.way_currency,
        "Tier": str(s.way_tier),
        "Interval": str(s.way_interval_ms),
    }
    config["Map"] = {"Hotkey": s.map_hotkey, "Interval": str(s.map_interval_ms)}
    config["Bag"] = {
        "CellSize": str(s.cell_size),
        "Rows": str(s.rows),
        "Cols": str(s.cols),
        "DumpInterval": str(s.dump_interval_ms),
    }
    cyclone_section: dict[str, str] = {}
    for key in CYC_KEYS:
        c = s.cyclone.get(key, default_key_config(key))
        cyclone_section[f"{key}_mode"] = c.mode
        cyclone_section[f"{key}_interval"] = str(c.interval_ms)
        cyclone_section[f"{key}_random"] = "1" if c.random_jitter else "0"
    for key in CYC_DETECT_KEYS:
        if key in s.cyclone_coords:
            p = s.cyclone_coords[key]
            cyclone_section[f"{key}_x"] = str(p.x)
            cyclone_section[f"{key}_y"] = str(p.y)
    config["Cyclone"] = cyclone_section

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
            c = s.profiles[i].get(key, default_key_config(key))
            section[f"{key}_mode"] = c.mode
            section[f"{key}_interval"] = str(c.interval_ms)
            section[f"{key}_random"] = "1" if c.random_jitter else "0"
        config[f"Profile{i + 1}"] = section

    config["Bridge"] = {"Enabled": "1" if s.bridge_enabled else "0", "Port": str(s.bridge_port)}

    ini.parent.mkdir(parents=True, exist_ok=True)
    with open(ini, "w", encoding="utf-8") as f:
        config.write(f)


# ============================================================
# 货币坐标推导
# ============================================================
def currency_coord(s: Settings, key: str, tier: int = 1) -> Point | None:
    """
    解析货币坐标：三级货币按级别向右偏移（二级 +70px，三级 +140px）。
    未标定返回 None。
    """
    if key not in s.currency:
        return None
    base = s.currency[key]
    dx = (tier - 1) * TIER_SPACING if key in TIERED_KEYS else 0
    return Point(base.x + dx, base.y)
