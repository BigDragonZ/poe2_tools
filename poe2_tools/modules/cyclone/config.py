#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风模块的 config.json 加载/保存/默认值合并（纯逻辑，可单测）。

- 默认配置与本文件同目录的 config.json（DEFAULT_CONFIG_PATH）
- 加载时做深合并：用户文件缺的字段一律回落到默认值
- 支持传入自定义路径；文件不存在或损坏时返回全默认配置（不崩溃）
"""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

# 默认配置文件路径（与本模块同目录）
DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "config.json"

# 内置默认值：与 config.json 保持一致，文件损坏/缺失时的兜底
DEFAULT_CONFIG: dict[str, Any] = {
    "system": {
        # 屏幕分辨率（用于 ROI 边界钳位上限）
        "resolution": [2560, 1440],
        # dxcam 目标采集帧率
        "capture_fps": 60,
        # 前台窗口校验周期（毫秒），非前台强制压入 IDLE
        "foreground_check_ms": 500,
        # 模式切换键（mouse 库命名：x2 = XButton2 侧键，用户习惯）
        "toggle_button": "x2",
    },
    "vision": {
        # Q/E 数字区与生命数值区（客户区坐标，2560×1440 基准）
        "q_roi": [1912, 1358, 1940, 1388],
        "e_roi": [1977, 1358, 2005, 1388],
        "life_roi": [65, 1052, 300, 1080],
        # 数字模板匹配度阈值（IoU）
        "match_confidence": 0.5,
        # 生命 OCR 节拍（毫秒，低频分支）
        "life_ocr_interval_ms": 500,
    },
    "loot": {
        # 以光标为中心的检测 ROI 边长（像素）
        "roi_size": 150,
        # HSV 黑色掩模：V 通道上限
        "black_v_max": 40,
        # 黑框长宽比筛选范围
        "aspect_ratio_min": 2.5,
        "aspect_ratio_max": 8.0,
        # 黑框面积筛选范围（像素）
        "area_min": 150,
        "area_max": 6000,
        # Canny 边缘检测阈值 [低, 高]
        "canny_threshold": [50, 150],
        # 矩形内部边缘像素占比下限（文本密度校验）
        "text_density_min": 0.08,
        # 光标锁定（漂移锁）时长（毫秒）
        "cursor_lock_ms": 30,
        # 消失监听期上限：超过则判定寻路失败进黑名单（毫秒）
        "pathfinding_timeout_ms": 600,
        # 消失监听期下限：至少观察这么久才算拾取成功（毫秒）
        "disappear_min_ms": 200,
        # 黑名单有效期（秒）
        "blacklist_cooldown_s": 5,
        # 黑名单坐标网格量化粒度（像素）
        "blacklist_grid_px": 32,
    },
    "combat": {
        # 接敌判定：Q 层数连续增长帧数
        "engage_growth_frames": 2,
        # 脱战判定：层数归零后无增长超时（秒）
        "disengage_timeout_s": 3.0,
        # Q 满层数（达到即释放）
        "q_max_stacks": 6,
        # Q 释放去抖（毫秒）
        "q_debounce_ms": 500,
        # E 满充能数（充能回满即释放）
        "e_full_charges": 3,
        # E 释放最小冷却间隔（秒）
        "e_cooldown_s": 4.0,
        # 低血喝药阈值（生命 当前/最大 比值）
        "life_threshold": 0.7,
        # 两次喝药最小间隔（秒）
        "flask_interval_s": 3.5,
        # 技能键位（硬编码 Q/E 格）与血瓶快捷键
        "q_key": "q",
        "e_key": "e",
        "flask_key": "1",
    },
}


def _deep_merge(default: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """深合并：override 中缺失的键用 default 补齐；类型不一致时回落默认值。"""
    merged: dict[str, Any] = {}
    for key, default_value in default.items():
        value = override.get(key)
        if isinstance(default_value, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(default_value, value)
        elif value is None or not isinstance(value, type(default_value)):
            merged[key] = copy.deepcopy(default_value)
        else:
            merged[key] = copy.deepcopy(value)
    return merged


def load_config(path: Path | str | None = None) -> dict[str, Any]:
    """
    加载配置并与默认值深合并。
    path 为 None 时用默认路径；文件不存在/损坏时返回全默认配置。
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    user_config: dict[str, Any] = {}
    if config_path.exists():
        try:
            data = json.loads(config_path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                user_config = data
        except (OSError, json.JSONDecodeError):
            user_config = {}
    return _deep_merge(DEFAULT_CONFIG, user_config)


def save_config(config: dict[str, Any], path: Path | str | None = None) -> Path:
    """保存配置（与默认值深合并后写盘，保证字段完整），返回写入路径。"""
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    merged = _deep_merge(DEFAULT_CONFIG, config if isinstance(config, dict) else {})
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(merged, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return config_path
