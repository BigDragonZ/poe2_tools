#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""输入记录分析（modules/recorder/analysis.py）纯逻辑单元测试。"""

from __future__ import annotations

import json

from poe2_tools.modules.recorder.analysis import (
    MIN_PRESS_INTERVAL_S,
    analyze_round,
    filter_events,
    load_rounds,
    render_report,
    session_active_time,
    split_sessions,
    summarize,
)


def _key(name: str, t: float) -> dict:
    return {"t": t, "kind": "key", "name": name}


def _mouse(name: str, t: float) -> dict:
    return {"t": t, "kind": "mouse", "name": name, "x": 100, "y": 200}


# ------------------------------------------------------------
# filter_events：过滤长按自动重复 / 抖动
# ------------------------------------------------------------
def test_filter_drops_key_auto_repeat() -> None:
    events = [_key("q", 1.0), _key("q", 1.0 + MIN_PRESS_INTERVAL_S / 2), _key("q", 1.5)]
    valid, dropped = filter_events(events)
    assert dropped == 1
    assert [e["t"] for e in valid] == [1.0, 1.5]


def test_filter_tracks_keys_independently() -> None:
    # Q/E 间隔再近也互不影响；鼠标与键盘同名也不同键位
    events = [_key("q", 1.0), _key("e", 1.01), _mouse("q", 1.02)]
    valid, dropped = filter_events(events)
    assert dropped == 0
    assert len(valid) == 3


def test_filter_sorts_and_compares_against_kept() -> None:
    # 乱序输入先排序；与「上一保留事件」比较，链式重复只留第一次
    events = [_key("q", 1.06), _key("q", 1.0), _key("q", 1.03)]
    valid, dropped = filter_events(events)
    assert dropped == 2
    assert [e["t"] for e in valid] == [1.0]


# ------------------------------------------------------------
# split_sessions：停顿切分 + 碎片丢弃
# ------------------------------------------------------------
def test_split_sessions_by_gap() -> None:
    events = [_key("q", 0.0), _key("q", 6.0), _key("q", 30.0), _key("q", 36.0)]
    sessions = split_sessions(events)
    assert len(sessions) == 2
    assert session_active_time(sessions) == 12.0


def test_split_sessions_drops_short_fragment() -> None:
    # 第一段仅 2 秒（< 5s 碎片），丢弃；第二段 6 秒保留
    events = [_key("q", 0.0), _key("q", 2.0), _key("q", 30.0), _key("q", 36.0)]
    sessions = split_sessions(events)
    assert len(sessions) == 1
    assert sessions[0][0]["t"] == 30.0


def test_split_sessions_empty() -> None:
    assert split_sessions([]) == []


# ------------------------------------------------------------
# analyze_round / summarize：频率与间隔统计
# ------------------------------------------------------------
def _sample_events() -> list[dict]:
    # 片段1：q@0、q@0.03(重复)、q@3、e@6（6s）；停顿 14s；片段2：q@20、q@23、e@26（6s）
    return [
        _key("q", 0.0),
        _key("q", 0.03),
        _key("q", 3.0),
        _key("e", 6.0),
        _key("q", 20.0),
        _key("q", 23.0),
        _key("e", 26.0),
    ]


def test_analyze_round() -> None:
    report = analyze_round("round-test.json", _sample_events())
    assert report.raw_events == 7
    assert report.invalid_events == 1
    assert report.sessions == 2
    assert report.active_time_s == 12.0
    q_stat = report.stats[("key", "q")]
    assert q_stat.presses == 4
    assert q_stat.intervals == [3.0, 3.0]
    e_stat = report.stats[("key", "e")]
    assert e_stat.presses == 2
    assert e_stat.intervals == []


def test_summarize_frequency_uses_active_time() -> None:
    summary = summarize([analyze_round("r1", _sample_events())])
    assert summary.rounds == 1
    assert summary.total_events == 7
    assert summary.invalid_events == 1
    assert summary.active_time_s == 12.0
    q_stat = summary.stats[("key", "q")]
    # 活跃 12 秒按 4 次 = 20 次/分；停顿的 14 秒不计入分母
    assert q_stat.presses / summary.active_time_s * 60 == 20.0


def test_analyze_empty_round() -> None:
    report = analyze_round("empty", [])
    assert report.sessions == 0
    assert report.active_time_s == 0.0
    assert report.stats == {}


# ------------------------------------------------------------
# load_rounds / render_report：文件读取与报告渲染
# ------------------------------------------------------------
def test_load_rounds_and_render(tmp_path) -> None:
    payload = {"version": 1, "started_at": "2026-10-02T15:00:00.000", "events": _sample_events()}
    (tmp_path / "round-20261002-150000-000.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    (tmp_path / "round-bad.json").write_text("not json", encoding="utf-8")  # 坏文件跳过

    reports = load_rounds(tmp_path)
    assert len(reports) == 1
    text = render_report(summarize(reports))
    assert "记录轮数：1" in text
    assert "Q 技能" in text
    assert "E 技能" in text
    assert "20.0" in text  # Q = 20 次/分


def test_render_report_no_events() -> None:
    text = render_report(summarize([analyze_round("empty", [])]))
    assert "没有任何按键事件" in text
