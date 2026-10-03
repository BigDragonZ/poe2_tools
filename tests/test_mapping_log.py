#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""刷图执行日志与 Q=6 热重载单元测试。"""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from poe2_tools.config.settings import Settings
from poe2_tools.modules.mapping import mlog
from poe2_tools.modules.mapping.assistant import (
    Q6_RETRY_INTERVAL_S,
    MappingAssistant,
    format_actions,
)
from poe2_tools.modules.mapping.fsm import Action, ActionKind


def _make_assistant(q6_roi: tuple[int, int, int, int] | None = (2100, 1350, 2124, 1370),
                    tmp_path: Path | None = None) -> MappingAssistant:
    settings = Settings()
    settings.combat.q6_roi = q6_roi
    config_path = (tmp_path / "config.json") if tmp_path is not None else None
    return MappingAssistant(settings, config_path=config_path)


def _write_q6_template(path: Path) -> None:
    """写一个合法的 q6 模板（暗底白字 6）。"""
    img = np.full((20, 24, 3), 30, dtype=np.uint8)
    cv2.putText(img, "6", (4, 16), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
    cv2.imwrite(str(path), img)


# ============================================================
# 文件日志器
# ============================================================
def test_file_logger_creates_dir_and_writes(tmp_path: Path) -> None:
    log_path = tmp_path / "logs" / "mapping.log"
    logger = mlog.get_file_logger(log_path)
    logger.info("测试消息")
    assert log_path.exists()
    content = log_path.read_text(encoding="utf-8")
    assert "测试消息" in content and "[INFO]" in content


def test_file_logger_no_duplicate_handlers(tmp_path: Path) -> None:
    log_path = tmp_path / "mapping.log"
    first = mlog.get_file_logger(log_path)
    count = len(first.handlers)
    second = mlog.get_file_logger(log_path)
    assert first is second
    assert len(first.handlers) == count  # 同路径重复调用不新增 handler


# ============================================================
# reload_q6 热重载
# ============================================================
def test_reload_q6_enables_after_calibration(tmp_path: Path) -> None:
    """先禁用（无模板）→ 标定产出模板后 reload → 立即启用，无需重启。"""
    template = tmp_path / "q6.png"
    a = _make_assistant(tmp_path=tmp_path)
    assert a.reload_q6(template, quiet=True) is False  # 模板不存在
    assert a.status()["q_enabled"] is False
    _write_q6_template(template)  # 模拟 F5 标定产出
    assert a.reload_q6(template, quiet=True) is True
    assert a.status()["q_enabled"] is True


def test_reload_q6_disabled_without_roi(tmp_path: Path) -> None:
    """未标定 ROI 时即使有模板也保持禁用。"""
    template = tmp_path / "q6.png"
    _write_q6_template(template)
    a = _make_assistant(q6_roi=None, tmp_path=tmp_path)
    assert a.reload_q6(template, quiet=True) is False
    assert a.status()["q_enabled"] is False


def test_reload_q6_idempotent(tmp_path: Path) -> None:
    """重复热重载不改变启用状态。"""
    template = tmp_path / "q6.png"
    _write_q6_template(template)
    a = _make_assistant(tmp_path=tmp_path)
    assert a.reload_q6(template, quiet=True) is True
    assert a.reload_q6(template, quiet=True) is True


# ============================================================
# 禁用时自动重试节流判定
# ============================================================
def test_q6_retry_throttle(tmp_path: Path) -> None:
    a = _make_assistant(q6_roi=None, tmp_path=tmp_path)
    a._q6_next_retry = 10.0
    assert not a.q6_retry_due(5.0)   # 未到点
    assert a.q6_retry_due(10.0)      # 到点
    a._q6_next_retry = 10.0 + Q6_RETRY_INTERVAL_S
    assert not a.q6_retry_due(11.0)


def test_q6_retry_not_due_when_enabled(tmp_path: Path) -> None:
    """掩模已启用时不再重试。"""
    template = tmp_path / "q6.png"
    _write_q6_template(template)
    a = _make_assistant(tmp_path=tmp_path)
    a.reload_q6(template, quiet=True)
    a._q6_next_retry = 0.0
    assert not a.q6_retry_due(999.0)


# ============================================================
# 动作链摘要
# ============================================================
def test_format_actions() -> None:
    actions = [
        Action(ActionKind.RELEASE_LEFT),
        Action(ActionKind.LOCK_CURSOR, x=1234, y=567, duration_ms=30),
        Action(ActionKind.CLICK_LEFT),
    ]
    assert format_actions(actions) == "RELEASE_LEFT→LOCK_CURSOR(1234,567,30ms)→CLICK_LEFT"
    combo = [
        Action(ActionKind.RELEASE_LEFT),
        Action(ActionKind.PRESS_KEY, key="e"),
        Action(ActionKind.WAIT, duration_ms=60),
        Action(ActionKind.PRESS_KEY, key="q"),
    ]
    assert format_actions(combo) == "RELEASE_LEFT→PRESS_E→WAIT(60ms)→PRESS_Q"
