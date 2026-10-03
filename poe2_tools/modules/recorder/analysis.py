#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
输入记录分析：从多轮记录中提取技能释放频率，过滤无效操作。

无效操作过滤规则：
1. 同键/同键位两次按下间隔 < MIN_PRESS_INTERVAL_S
   → 键盘长按自动重复、鼠标连点抖动，只保留第一次
2. 相邻事件间隔 > SESSION_GAP_S 处切开活跃片段
   → 回城/喝水/查价等停顿时间不计入施放频率分母
3. 片段时长 < MIN_SESSION_DURATION_S 的碎片丢弃
   → 误触 F2、刚起手就停止等无效轮段

事件格式见 recorder.py：{"t": 相对秒, "kind": "key"|"mouse", "name": "q"|"left"|...}
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from pathlib import Path

# 同键最小按下间隔（秒）：低于此值视为自动重复/抖动，丢弃
MIN_PRESS_INTERVAL_S = 0.08
# 活跃片段切分间隔（秒）：相邻事件间隔超过此值切为两段
SESSION_GAP_S = 10.0
# 片段最短时长（秒）：低于此值的碎片片段不计入统计
MIN_SESSION_DURATION_S = 5.0

# 显示名映射
DISPLAY_NAMES = {
    "q": "Q 技能",
    "e": "E 技能",
    "left": "鼠标左键",
    "right": "鼠标右键",
    "middle": "鼠标中键",
    "x": "鼠标侧键1",
    "x2": "鼠标侧键2",
}


@dataclass
class KeyStat:
    """单个键/键位的聚合统计。"""

    kind: str
    name: str
    presses: int = 0
    intervals: list[float] = field(default_factory=list)


@dataclass
class RoundReport:
    """单轮分析结果。"""

    source: str
    raw_events: int
    invalid_events: int
    valid_events: int
    sessions: int
    active_time_s: float
    stats: dict[tuple[str, str], KeyStat]


@dataclass
class Summary:
    """多轮汇总结果。"""

    rounds: int
    total_events: int
    invalid_events: int
    active_time_s: float
    stats: dict[tuple[str, str], KeyStat]


# ============================================================
# 纯逻辑（单元测试目标）
# ============================================================
def filter_events(events: list[dict]) -> tuple[list[dict], int]:
    """按时间排序，丢弃与上一保留事件同名且间隔过短的按下。返回 (有效事件, 丢弃数)。"""
    ordered = sorted(events, key=lambda e: e["t"])
    valid: list[dict] = []
    last_t: dict[tuple[str, str], float] = {}
    dropped = 0
    for event in ordered:
        key = (event["kind"], event["name"])
        prev = last_t.get(key)
        if prev is not None and event["t"] - prev < MIN_PRESS_INTERVAL_S:
            dropped += 1
            continue
        last_t[key] = event["t"]
        valid.append(event)
    return valid, dropped


def split_sessions(
    events: list[dict],
    gap: float = SESSION_GAP_S,
    min_duration: float = MIN_SESSION_DURATION_S,
) -> list[list[dict]]:
    """按事件间隔切分活跃片段，丢弃过短的碎片片段。events 需已按时间排序。"""
    if not events:
        return []
    sessions: list[list[dict]] = []
    current = [events[0]]
    for prev, cur in zip(events, events[1:]):
        if cur["t"] - prev["t"] > gap:
            sessions.append(current)
            current = []
        current.append(cur)
    sessions.append(current)
    return [s for s in sessions if s[-1]["t"] - s[0]["t"] >= min_duration]


def session_active_time(sessions: list[list[dict]]) -> float:
    """活跃总时长 = 各片段首尾时间差之和。"""
    return sum(s[-1]["t"] - s[0]["t"] for s in sessions)


def _accumulate(stats: dict[tuple[str, str], KeyStat], events: list[dict]) -> None:
    """把一个片段内的事件并入统计：按键计数 + 同名相邻间隔。"""
    by_name: dict[tuple[str, str], list[float]] = {}
    for event in events:
        by_name.setdefault((event["kind"], event["name"]), []).append(event["t"])
    for key, times in by_name.items():
        stat = stats.setdefault(key, KeyStat(kind=key[0], name=key[1]))
        stat.presses += len(times)
        stat.intervals.extend(b - a for a, b in zip(times, times[1:]))


def analyze_round(source: str, events: list[dict]) -> RoundReport:
    """分析单轮事件列表。"""
    valid, invalid = filter_events(events)
    sessions = split_sessions(valid)
    stats: dict[tuple[str, str], KeyStat] = {}
    for session in sessions:
        _accumulate(stats, session)
    return RoundReport(
        source=source,
        raw_events=len(events),
        invalid_events=invalid,
        valid_events=len(valid),
        sessions=len(sessions),
        active_time_s=session_active_time(sessions),
        stats=stats,
    )


def summarize(rounds: list[RoundReport]) -> Summary:
    """多轮汇总：计数、间隔合并，活跃时长相加。"""
    stats: dict[tuple[str, str], KeyStat] = {}
    for report in rounds:
        for key, stat in report.stats.items():
            merged = stats.setdefault(key, KeyStat(kind=key[0], name=key[1]))
            merged.presses += stat.presses
            merged.intervals.extend(stat.intervals)
    return Summary(
        rounds=len(rounds),
        total_events=sum(r.raw_events for r in rounds),
        invalid_events=sum(r.invalid_events for r in rounds),
        active_time_s=sum(r.active_time_s for r in rounds),
        stats=stats,
    )


# ============================================================
# 读取与报告
# ============================================================
def load_rounds(record_dir: Path | str) -> list[RoundReport]:
    """读取目录下全部轮次 JSON 并逐轮分析。"""
    directory = Path(record_dir)
    reports = []
    for path in sorted(directory.glob("round-*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        events = payload.get("events")
        if isinstance(events, list):
            reports.append(analyze_round(path.name, events))
    return reports


def _per_minute(presses: int, active_time_s: float) -> float:
    return presses / active_time_s * 60 if active_time_s > 0 else 0.0


def render_report(summary: Summary) -> str:
    """把汇总结果渲染为中文文本报告。"""
    lines = [
        f"记录轮数：{summary.rounds}，总事件：{summary.total_events}，"
        f"过滤无效：{summary.invalid_events}",
        f"活跃总时长：{summary.active_time_s / 60:.1f} 分钟"
        f"（已排除 >{SESSION_GAP_S:.0f}s 的停顿与 <{MIN_SESSION_DURATION_S:.0f}s 的碎片）",
        "",
        f"{'键位':<10}{'次数':>6}{'次/分':>8}{'中位间隔':>10}{'平均间隔':>10}",
    ]
    for key in sorted(summary.stats):
        stat = summary.stats[key]
        name = DISPLAY_NAMES.get(stat.name, stat.name)
        per_min = _per_minute(stat.presses, summary.active_time_s)
        median = f"{statistics.median(stat.intervals):.2f}s" if stat.intervals else "-"
        mean = f"{statistics.mean(stat.intervals):.2f}s" if stat.intervals else "-"
        lines.append(f"{name:<10}{stat.presses:>6}{per_min:>8.1f}{median:>10}{mean:>10}")
    if len(lines) == 4:
        lines.append("（有效片段内没有任何按键事件）")
    return "\n".join(lines)
