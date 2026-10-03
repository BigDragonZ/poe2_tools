#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刷图自动化模块：极简健康刷图（三线程生产者-消费者 + 确定性 FSM）。

__init__ 只导出纯逻辑（fsm）；assistant/capture/input_exec 依赖
桌面环境（dxcam / SendInput / 全局钩子），由使用方显式导入，
保证纯逻辑单测不触碰桌面 API。
"""

from poe2_tools.modules.mapping.fsm import (
    Action,
    ActionKind,
    Blacklist,
    FrameSignals,
    MappingFSM,
    State,
)

__all__ = [
    "Action",
    "ActionKind",
    "Blacklist",
    "FrameSignals",
    "MappingFSM",
    "State",
]
