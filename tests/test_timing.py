#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""时间规约与连点调度器单元测试。"""

from __future__ import annotations

from poe2_tools.config.settings import MIN_INTERVAL_MS
from poe2_tools.core.scheduler import JITTER_RATIO, SpamScheduler
from poe2_tools.core.timing import clamp, jitter_ms


# ============================================================
# 抖动
# ============================================================
def test_jitter_bounds() -> None:
    for r in (0.0, 0.25, 0.5, 0.75, 0.999):
        value = jitter_ms(100, 0.3, r)
        assert round(100 * 0.7) <= value <= round(100 * 1.3)


def test_jitter_extremes() -> None:
    assert jitter_ms(200, 0.15, 0.0) == 170
    assert jitter_ms(200, 0.15, 1.0) == 230


def test_clamp() -> None:
    assert clamp(5, 1, 10) == 5
    assert clamp(0, 1, 10) == 1
    assert clamp(99, 1, 10) == 10


# ============================================================
# 调度器
# ============================================================
def test_start_staggers_first_due_within_interval() -> None:
    scheduler = SpamScheduler(rng=lambda: 0.5)
    scheduler.start({"q": 1000, "w": 200}, now=10.0)
    assert scheduler.collect_due(10.0) == []
    assert scheduler.collect_due(10.1) == ["w"]  # 200ms * 0.5
    assert sorted(scheduler.collect_due(10.5)) == ["q", "w"]


def test_reschedule_without_jitter() -> None:
    scheduler = SpamScheduler(rng=lambda: 0.0)
    scheduler.start({"q": 500}, now=0.0)
    scheduler.reschedule("q", 500, random_jitter=False, now=1.0)
    assert scheduler.collect_due(1.4) == []
    assert scheduler.collect_due(1.5) == ["q"]


def test_reschedule_jitter_within_ratio() -> None:
    for r in (0.0, 0.5, 1.0):
        scheduler = SpamScheduler(rng=lambda: r)
        scheduler.start({"q": 1000}, now=0.0)
        scheduler.reschedule("q", 1000, random_jitter=True, now=5.0)
        lo = 5.0 + 1000 * (1 - JITTER_RATIO) / 1000.0
        hi = 5.0 + 1000 * (1 + JITTER_RATIO) / 1000.0
        assert scheduler.collect_due(lo - 0.001) == []
        assert scheduler.collect_due(hi + 0.001) == ["q"]


def test_reschedule_enforces_min_interval() -> None:
    scheduler = SpamScheduler(rng=lambda: 0.0)
    scheduler.start({"q": 10}, now=0.0)
    scheduler.reschedule("q", 10, random_jitter=False, now=0.0)
    assert scheduler.collect_due(MIN_INTERVAL_MS / 1000.0 - 0.001) == []
    assert scheduler.collect_due(MIN_INTERVAL_MS / 1000.0) == ["q"]


def test_stop_clears_state() -> None:
    scheduler = SpamScheduler(rng=lambda: 0.0)
    scheduler.start({"q": 100}, now=0.0)
    scheduler.stop()
    assert scheduler.collect_due(99.0) == []
