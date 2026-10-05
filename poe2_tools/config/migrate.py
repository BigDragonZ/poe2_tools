#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
AHK 配置迁移：把 ahk/poe2_key_helper.ini 迁移为新格式 poe2_tools.ini。

AHK 版 ini 是混合编码文件（UTF-8 BOM + GBK 节名「配置N」），
需要逐行容错解码；模式字段由整数（1/2/3）转换为字符串
（disabled/spam/hold）；FindText 字库代码（q_text/e_text）为
AHK 私有格式，无法移植，迁移时丢弃（由新版「截图」按钮重新生成模板）。
"""

from __future__ import annotations

import configparser
import io
from pathlib import Path

from poe2_tools.config.settings import (
    CURRENCY_KEYS,
    PROFILE_COUNT,
    SKILL_KEYS,
    KeyConfig,
    Point,
    Settings,
    default_key_config,
    save_settings,
)

# AHK 模式整数 -> 新版模式字符串
_MODE_MAP = {"1": "disabled", "2": "spam", "3": "hold"}


def decode_ahk_ini(raw: bytes) -> str:
    """逐行容错解码混合编码 ini：优先 UTF-8，失败回退 GBK。"""
    text = raw.decode("utf-8-sig", errors="strict") if _is_pure_utf8(raw) else None
    if text is not None:
        return text
    if raw.startswith(b"\xef\xbb\xbf"):  # 去掉 UTF-8 BOM 再逐行解码
        raw = raw[3:]
    lines: list[str] = []
    for raw_line in raw.split(b"\n"):
        line = raw_line.rstrip(b"\r")
        try:
            lines.append(line.decode("utf-8"))
        except UnicodeDecodeError:
            lines.append(line.decode("gbk", errors="replace"))
    return "\n".join(lines)


def _is_pure_utf8(raw: bytes) -> bool:
    try:
        raw.decode("utf-8-sig")
        return True
    except UnicodeDecodeError:
        return False


def _get(config: configparser.ConfigParser, section: str, key: str) -> str:
    return config.get(section, key, fallback="").strip()


def _get_int(config: configparser.ConfigParser, section: str, key: str, default: int) -> int:
    try:
        return int(_get(config, section, key))
    except ValueError:
        return default


def _migrate_key_config(
    config: configparser.ConfigParser, section: str, key: str, default: KeyConfig
) -> KeyConfig:
    mode = _MODE_MAP.get(_get(config, section, f"{key}_mode"), default.mode)
    interval = _get_int(config, section, f"{key}_interval", default.interval_ms)
    # AHK 的 ±15% 比例抖动（0/1 开关）折算为等效毫秒数
    random_on = _get_int(config, section, f"{key}_random", 1) == 1
    jitter_ms = round(interval * 0.15) if random_on else 0
    return KeyConfig(mode, interval, jitter_ms)


def migrate_ahk_config(raw: bytes) -> Settings:
    """把 AHK ini 原始字节解析为新版 Settings（纯逻辑，便于测试）。"""
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read_file(io.StringIO(decode_ahk_ini(raw)))

    s = Settings()
    s.combat.hotkey = _get(config, "General", "CombatHotkey") or s.combat.hotkey
    s.general.sort.hotkey = _get(config, "General", "DumpHotkey") or s.general.sort.hotkey
    s.combat.active_profile = _get_int(config, "General", "ActiveProfile", 1)

    s.general.tablet.hotkey = _get(config, "Waystone", "Hotkey") or s.general.tablet.hotkey
    s.general.tablet.currency = _get(config, "Waystone", "Currency") or s.general.tablet.currency
    s.general.tablet.tier = _get_int(config, "Waystone", "Tier", 1)
    s.general.tablet.interval_ms = _get_int(
        config, "Waystone", "Interval", s.general.tablet.interval_ms
    )

    s.general.map_click.hotkey = _get(config, "Map", "Hotkey") or s.general.map_click.hotkey
    s.general.map_click.interval_ms = _get_int(
        config, "Map", "Interval", s.general.map_click.interval_ms
    )

    s.general.sort.cell_size = _get_int(config, "Bag", "CellSize", 0)
    s.general.sort.rows = _get_int(config, "Bag", "Rows", s.general.sort.rows)
    s.general.sort.cols = _get_int(config, "Bag", "Cols", s.general.sort.cols)
    s.general.sort.interval_ms = _get_int(
        config, "Bag", "DumpInterval", s.general.sort.interval_ms
    )

    for key in CURRENCY_KEYS:
        x, y = _get(config, "Currency", f"{key}_x"), _get(config, "Currency", f"{key}_y")
        if x and y:
            s.currency[key] = Point(int(x), int(y))

    for i in range(PROFILE_COUNT):
        section = f"配置{i + 1}"  # GBK 节名解码后为「配置N」
        profile: dict[str, KeyConfig] = {}
        for key in SKILL_KEYS:
            profile[key] = _migrate_key_config(config, section, key, default_key_config(key))
        s.combat.profiles[i] = profile

    return s


def migrate_file(ahk_ini: Path, target_ini: Path) -> Settings | None:
    """
    执行迁移：读取 AHK ini → 写入新 ini；AHK 文件不存在时返回 None。
    迁移成功不删除源文件（由用户确认后统一清理 ahk/ 目录）。
    """
    if not ahk_ini.exists():
        return None
    settings = migrate_ahk_config(ahk_ini.read_bytes())
    save_settings(settings, target_ini)
    return settings


def merge_ahk_coords(settings: Settings, raw: bytes) -> list[str]:
    """
    增量合并 AHK ini 中的货币坐标到现有配置。
    只填充当前未标定的项，不覆盖已有坐标与其他配置。
    返回本次同步的项目名列表（如 ["currency:alch"]）。
    """
    config = configparser.ConfigParser()
    config.optionxform = str
    config.read_file(io.StringIO(decode_ahk_ini(raw)))

    synced: list[str] = []
    for key in CURRENCY_KEYS:
        if key in settings.currency:
            continue
        x, y = _get(config, "Currency", f"{key}_x"), _get(config, "Currency", f"{key}_y")
        if x and y:
            settings.currency[key] = Point(int(x), int(y))
            synced.append(f"currency:{key}")
    return synced


def merge_ahk_coords_file(settings: Settings, ahk_ini: Path) -> list[str]:
    """从 AHK ini 文件增量合并坐标；文件不存在时返回空列表。"""
    if not ahk_ini.exists():
        return []
    return merge_ahk_coords(settings, ahk_ini.read_bytes())
