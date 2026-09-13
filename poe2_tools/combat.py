#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
POE2 游玩工具 - 战斗巡航（连点宏）

按配置周期自动触发技能按键：
- 支持鼠标左/右键、空格、Q/W/E/R
- 策略：禁用 / 连点（按间隔触发）/ 按住不放
- 全局热键切换启动/停止（默认 F2），POE2 窗口失焦自动停止

配置存于 poe2_tools.ini 的 [Combat] 节（UTF-8 编码）。
仅使用输入模拟，不读取游戏内存、不注入、不 Hook。
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass

import pydirectinput

from poe2_tools import common

# ============================================================
# 常量配置
# ============================================================
# 支持的按键：内部标识 -> 界面显示名称（顺序即界面展示顺序）
KEYS: list[tuple[str, str]] = [
    ("left", "鼠标左键"),
    ("right", "鼠标右键"),
    ("space", "空格"),
    ("q", "Q"),
    ("w", "W"),
    ("e", "E"),
    ("r", "R"),
]

# 支持的策略：内部标识 -> 界面显示名称
MODES: list[tuple[str, str]] = [
    ("disabled", "禁用"),
    ("spam", "连点"),
    ("hold", "按住不放"),
]

# 战斗启动/停止热键默认值（存于 poe2_tools.ini [Combat] ToggleKey）
DEFAULT_TOGGLE_HOTKEY = "f2"

DEFAULT_INTERVAL_MS = 300
MIN_INTERVAL_MS = 50

# 连点间隔随机抖动比例，避免机械化特征
JITTER_RATIO = 0.15

# 主循环节拍（秒），决定触发精度
LOOP_TICK = 0.01

_MOUSE_BUTTONS = {"left", "right"}


def _emit(message: str, logger: Callable[[str], None] | None) -> None:
    """向控制台和可选的 logger 同时输出消息。"""
    common._emit(message, logger)


# ============================================================
# 技能配置
# ============================================================
@dataclass
class SkillConfig:
    """单个按键的战斗配置。"""

    key_id: str
    mode: str = "disabled"
    interval_ms: int = DEFAULT_INTERVAL_MS


def load_skills() -> list[SkillConfig]:
    """从 poe2_tools.ini 读取全部按键配置；默认鼠标左键连点，其余禁用。"""
    config = common.load_config()
    skills: list[SkillConfig] = []
    for key_id, _ in KEYS:
        default_mode = "spam" if key_id == "left" else "disabled"
        mode = config.get("Combat", f"{key_id}_mode", fallback=default_mode).strip()
        if mode not in {m for m, _ in MODES}:
            mode = default_mode
        try:
            interval = config.getint(
                "Combat", f"{key_id}_interval", fallback=DEFAULT_INTERVAL_MS
            )
        except ValueError:
            interval = DEFAULT_INTERVAL_MS
        skills.append(SkillConfig(key_id, mode, max(interval, MIN_INTERVAL_MS)))
    return skills


def save_skills(skills: list[SkillConfig]) -> None:
    """把全部按键配置写入 poe2_tools.ini。"""
    config = common.load_config()
    if not config.has_section("Combat"):
        config.add_section("Combat")
    for skill in skills:
        config.set("Combat", f"{skill.key_id}_mode", skill.mode)
        config.set("Combat", f"{skill.key_id}_interval", str(skill.interval_ms))
    common.save_config(config)


def get_toggle_hotkey() -> str:
    """读取战斗启动/停止热键，未配置时返回默认值。"""
    config = common.load_config()
    hotkey = config.get("Combat", "ToggleKey", fallback=DEFAULT_TOGGLE_HOTKEY).strip()
    return hotkey or DEFAULT_TOGGLE_HOTKEY


def set_toggle_hotkey(hotkey: str) -> None:
    """保存战斗启动/停止热键。"""
    config = common.load_config()
    if not config.has_section("Combat"):
        config.add_section("Combat")
    config.set("Combat", "ToggleKey", hotkey.strip())
    common.save_config(config)


# ============================================================
# 输入触发
# ============================================================
def _press(key_id: str) -> None:
    """点按一次指定按键。"""
    if key_id in _MOUSE_BUTTONS:
        pydirectinput.click(button=key_id)
    else:
        pydirectinput.press(key_id)


def _hold_down(key_id: str) -> None:
    """按住指定按键（不释放）。"""
    if key_id in _MOUSE_BUTTONS:
        pydirectinput.mouseDown(button=key_id)
    else:
        pydirectinput.keyDown(key_id)


def release_all() -> None:
    """释放所有可能被按住的按键。"""
    for key_id, _ in KEYS:
        try:
            if key_id in _MOUSE_BUTTONS:
                pydirectinput.mouseUp(button=key_id)
            else:
                pydirectinput.keyUp(key_id)
        except Exception:
            pass


# ============================================================
# 战斗宏
# ============================================================
class CombatMacro:
    """战斗巡航：启动后按各按键配置周期触发，直到停止或 POE2 失焦。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._skills: list[SkillConfig] = []
        self.active = False

    def toggle(self, logger: Callable[[str], None] | None = None) -> None:
        """切换启动/停止。"""
        if self.active:
            self.stop(logger)
        else:
            self.start(logger=logger)

    def start(self, logger: Callable[[str], None] | None = None) -> None:
        """启动战斗宏（后台线程执行）。"""
        with self._lock:
            if self.active:
                _emit("战斗宏已在运行中，忽略本次触发。", logger)
                return
            if not common.is_poe_active():
                _emit("未检测到 Path of Exile 2 前台窗口，取消启动。", logger)
                return

            self._skills = load_skills()
            enabled = [s for s in self._skills if s.mode != "disabled"]
            if not enabled:
                _emit("所有按键均为禁用状态，请先在战斗页配置战斗设置。", logger)
                return

            self.active = True
            self._stop.clear()

        threading.Thread(target=self._run, args=(logger,), daemon=True).start()

    def stop(self, logger: Callable[[str], None] | None = None) -> None:
        """停止战斗宏并释放所有按键。"""
        if self.active:
            _emit("停止战斗宏。", logger)
        self._stop.set()
        release_all()

    # --------------------------------------------------------
    # 后台主循环
    # --------------------------------------------------------
    def _run(self, logger: Callable[[str], None] | None) -> None:
        spam_skills = [s for s in self._skills if s.mode == "spam"]
        hold_skills = [s for s in self._skills if s.mode == "hold"]

        key_names = dict(KEYS)
        parts = [f"{key_names[s.key_id]}(连点 {s.interval_ms}ms)" for s in spam_skills]
        parts += [f"{key_names[s.key_id]}(按住)" for s in hold_skills]
        _emit(f"战斗宏已启动: {', '.join(parts)}", logger)

        try:
            # 先按住所有 hold 按键
            for skill in hold_skills:
                _hold_down(skill.key_id)

            # 首次触发错开一点，避免所有按键同一帧打出
            now = time.monotonic()
            next_due = {
                s.key_id: now + random.uniform(0, s.interval_ms / 1000.0)
                for s in spam_skills
            }

            while not self._stop.is_set():
                if not common.is_poe_active():
                    _emit("POE2 窗口失去焦点，自动停止战斗宏。", logger)
                    break

                now = time.monotonic()
                for skill in spam_skills:
                    if now >= next_due[skill.key_id]:
                        _press(skill.key_id)
                        jitter = skill.interval_ms * JITTER_RATIO
                        interval = skill.interval_ms + random.uniform(-jitter, jitter)
                        next_due[skill.key_id] = now + max(interval, MIN_INTERVAL_MS) / 1000.0

                time.sleep(LOOP_TICK)
        finally:
            release_all()
            with self._lock:
                self.active = False
            self._stop.clear()
            _emit("战斗宏已停止。", logger)
