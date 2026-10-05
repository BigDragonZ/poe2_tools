#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风模块：赶路 + 接敌连招 + 拾取 + 低血喝药（三线程生产者-消费者 + 确定性 FSM）。

__init__ 只导出纯逻辑（fsm/vision）；engine/capture/executor 依赖
桌面环境（dxcam / SendInput / 全局钩子），由使用方显式导入，
保证纯逻辑单测不触碰桌面 API。
"""

from poe2_tools.modules.cyclone.fsm import (
    Action,
    ActionKind,
    Blacklist,
    CycloneFSM,
    FrameSignals,
    State,
)
from poe2_tools.modules.cyclone.vision import (
    DigitState,
    TemplateLibrary,
    classify_digit,
    load_templates,
    parse_life_text,
)

__all__ = [
    "Action",
    "ActionKind",
    "Blacklist",
    "CycloneFSM",
    "DigitState",
    "FrameSignals",
    "State",
    "TemplateLibrary",
    "classify_digit",
    "load_templates",
    "parse_life_text",
]
