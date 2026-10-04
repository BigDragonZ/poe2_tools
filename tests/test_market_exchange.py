#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""默认/指定通货批量抓取：比例换算、通货对生成、抓取编排与按类别自动汇率替换写入。"""

from __future__ import annotations

import pytest

from poe2_tools.modules.market.exchange import (
    ExchangeScanRunner,
    auto_pairs,
    check_scan_consistency,
    custom_pairs,
    default_pairs,
    parse_ratio,
    rates_from_scan,
)
from poe2_tools.modules.market.scanner import UnsetCoordinateError
from web import db


# ============================================================
# 比例文本解析
# ============================================================
def test_parse_ratio_basic() -> None:
    assert parse_ratio("1:155") == (1.0, 155.0)
    assert parse_ratio("10.40:1") == (10.4, 1.0)


def test_parse_ratio_thousands_comma() -> None:
    assert parse_ratio("1:1,250") == (1.0, 1250.0)


def test_parse_ratio_invalid() -> None:
    assert parse_ratio("") is None
    assert parse_ratio("无比例") is None
    assert parse_ratio("1:0") is None
    assert parse_ratio("0:5") is None


# ============================================================
# scan 数据契约 → 交易助手汇率
# ============================================================
def _scan_result() -> dict:
    return {
        "success": True,
        "pair": "Divine Orb <-> Chaos Orb",
        "b_to_a": [{"rank": 1, "ratio": "1:155", "stock": 120}],
        "a_to_b": [{"rank": 1, "ratio": "158:1", "stock": 450}],
    }


def test_rates_from_scan_orientation() -> None:
    """A=Divine B=Chaos：b_to_a「1:155」→ 付 155 混沌买 1 神圣（买边）；
    a_to_b「158:1」→ 付 1 神圣买 158 混沌（买边）。"""
    rates = rates_from_scan(_scan_result(), "divine", "chaos")
    assert rates == [
        {"from_unit": "chaos", "to_unit": "divine",
         "amount_from": 155.0, "amount_to": 1.0, "side": "buy"},
        {"from_unit": "divine", "to_unit": "chaos",
         "amount_from": 1.0, "amount_to": 158.0, "side": "buy"},
    ]


def test_rates_from_scan_empty_direction_skipped() -> None:
    """某方向无挂单或比例无法解析 → 只保留另一方向。"""
    result = {"b_to_a": [], "a_to_b": [{"rank": 1, "ratio": "158:1", "stock": None}]}
    rates = rates_from_scan(result, "divine", "chaos")
    assert rates == [
        {"from_unit": "divine", "to_unit": "chaos",
         "amount_from": 1.0, "amount_to": 158.0, "side": "buy"},
    ]
    bad = {"b_to_a": [{"rank": 1, "ratio": "坏", "stock": None}], "a_to_b": []}
    assert rates_from_scan(bad, "divine", "chaos") == []


# ============================================================
# 通货对生成
# ============================================================
def test_default_pairs() -> None:
    pairs = default_pairs()
    units = [(p[0], p[2]) for p in pairs]
    assert units == [("exalted", "chaos"), ("exalted", "divine"), ("chaos", "divine")]
    names = {(p[1], p[3]) for p in pairs}
    assert ("Exalted Orb", "Chaos Orb") in names
    assert ("Chaos Orb", "Divine Orb") in names


def test_custom_pairs() -> None:
    pairs = custom_pairs("Orb of Annulment")
    assert len(pairs) == 3
    assert all(p[0] == "item:Orb of Annulment" for p in pairs)
    assert all(p[1] == "Orb of Annulment" for p in pairs)
    assert [p[2] for p in pairs] == ["exalted", "chaos", "divine"]


# ============================================================
# 抓取编排（假扫描器 + 记录型发布器）
# ============================================================
class FakeScanner:
    """按通货对返回预设结果的假扫描器；fail_on 中的对抛异常。"""

    def __init__(self, results: dict, fail_on: set | None = None) -> None:
        self._results = results
        self._fail_on = fail_on or set()
        self.calls: list[tuple[str, str]] = []

    def preflight(self) -> None:
        pass

    def scan(self, currency_a: str, currency_b: str) -> dict:
        self.calls.append((currency_a, currency_b))
        if (currency_a, currency_b) in self._fail_on:
            raise RuntimeError("模拟抓取失败")
        return self._results.get((currency_a, currency_b), {"b_to_a": [], "a_to_b": []})


class UnsetScanner:
    def preflight(self) -> None:
        raise UnsetCoordinateError("市场坐标未标定")

    def scan(self, a: str, b: str) -> dict:  # pragma: no cover - 不应被调用
        raise AssertionError("preflight 失败后不应执行 scan")


def test_runner_collects_and_publishes() -> None:
    """3 对全部成功：6 条双向汇率一次性发布（带类别），进度回调按对触发。"""
    scanner = FakeScanner({
        ("Exalted Orb", "Chaos Orb"): {
            "b_to_a": [{"rank": 1, "ratio": "1:10", "stock": 5}],
            "a_to_b": [{"rank": 1, "ratio": "11:1", "stock": 3}],
        },
    })
    published: list[tuple[str, list[dict]]] = []
    progress_log: list[str] = []
    runner = ExchangeScanRunner(
        scanner,
        publisher=lambda rates, category: published.append((category, rates)) or len(rates),
    )

    summary = runner.run(default_pairs(), category="custom", progress=progress_log.append)

    assert summary["pairs"] == 3
    assert summary["rates"] == 2  # 只有第一对有挂单
    assert summary["published"] == 2
    assert summary["category"] == "custom"
    assert summary["errors"] == []
    assert len(published) == 1 and len(published[0][1]) == 2
    assert published[0][0] == "custom"  # 类别透传给发布器
    assert len(progress_log) == 3
    # 买边方向：付混沌买崇高 / 付崇高买混沌
    assert published[0][1][0]["from_unit"] == "chaos"
    assert published[0][1][0]["to_unit"] == "exalted"
    assert published[0][1][1]["from_unit"] == "exalted"


def test_runner_continues_on_pair_failure() -> None:
    """单对抓取异常记入 errors 并继续；无任何比例时不发布。"""
    pairs = default_pairs()
    fail_pair = (pairs[0][1], pairs[0][3])
    scanner = FakeScanner({}, fail_on={fail_pair})
    published: list[tuple[str, list[dict]]] = []
    runner = ExchangeScanRunner(
        scanner, publisher=lambda rates, category: published.append((category, rates)) or 0
    )

    summary = runner.run(pairs)

    assert len(scanner.calls) == 3  # 失败不中断后续对
    assert len(summary["errors"]) == 1
    assert summary["published"] == 0
    assert published == []


def test_runner_preflight_raises() -> None:
    """坐标未标定：preflight 抛出且不产生任何抓取/发布。"""
    published: list[tuple[str, list[dict]]] = []
    runner = ExchangeScanRunner(
        UnsetScanner(), publisher=lambda r, c: published.append((c, r)) or 0
    )
    with pytest.raises(UnsetCoordinateError):
        runner.run(default_pairs())
    assert published == []


# ============================================================
# 自动汇率替换写入（web/db.py，临时库）
# ============================================================
def _rate(frm: str, to: str, amount_to: float) -> dict:
    return {"from_unit": frm, "to_unit": to,
            "amount_from": 1.0, "amount_to": amount_to, "side": "buy"}


def test_replace_auto_trade_rates_keeps_latest(tmp_path) -> None:
    """整批替换：同类别旧自动记录全部清除只留本批；手动记录不受影响。"""
    path = tmp_path / "eco.db"
    db.init_db(path)
    db.replace_auto_trade_rates([_rate("chaos", "divine", 150.0),
                                 _rate("exalted", "chaos", 65.0)], db_path=path)
    db.replace_auto_trade_rates([_rate("chaos", "divine", 155.0)], db_path=path)

    rows = [r for r in db.list_trade_rates(db_path=path)
            if r["from_unit"] == "chaos" and r["to_unit"] == "divine"]
    assert len(rows) == 1
    assert rows[0]["amount_to"] == 155.0
    assert rows[0]["source"] == "auto"
    # 上一批中本批未覆盖的方向一并清除（整批只留最近一次）
    assert [r for r in db.list_trade_rates(db_path=path)
            if r["from_unit"] == "exalted"] == []

    # 手动录入同方向：不被自动替换删除；latest 取 id 最大者（手动更新则手动生效）
    db.add_trade_rate("chaos", "divine", 1.0, 160.0, side="buy", db_path=path)
    db.replace_auto_trade_rates([_rate("chaos", "divine", 158.0)], db_path=path)
    rows = [r for r in db.list_trade_rates(db_path=path)
            if r["from_unit"] == "chaos" and r["to_unit"] == "divine"]
    assert len(rows) == 2  # 手动 + 自动各一
    latest = [r for r in db.latest_trade_rates(db_path=path)
              if r["from_unit"] == "chaos" and r["to_unit"] == "divine"]
    assert latest[0]["amount_to"] == 158.0  # 自动记录更新，参与最新计算


def test_add_trade_rate_default_source_manual(tmp_path) -> None:
    """手动录入接口默认 source='manual'、category='default'（页面入口已移除，接口保留）。"""
    path = tmp_path / "eco.db"
    db.init_db(path)
    db.add_trade_rate("exalted", "chaos", 1.0, 10.0, side="sell", db_path=path)
    row = db.list_trade_rates(db_path=path)[0]
    assert row["source"] == "manual"
    assert row["category"] == "default"


def test_replace_auto_trade_rates_category_isolated(tmp_path) -> None:
    """类别隔离：整批替换只清同类别旧自动记录；latest/list 可按类别过滤。"""
    path = tmp_path / "eco.db"
    db.init_db(path)
    db.replace_auto_trade_rates([_rate("chaos", "divine", 150.0)], db_path=path)
    db.replace_auto_trade_rates(
        [_rate("item:Orb of Annulment", "chaos", 3.0)], category="custom", db_path=path)

    defaults = db.latest_trade_rates("default", db_path=path)
    customs = db.latest_trade_rates("custom", db_path=path)
    assert [r["to_unit"] for r in defaults] == ["divine"]
    assert [r["from_unit"] for r in customs] == ["item:Orb of Annulment"]
    assert customs[0]["category"] == "custom"

    # 同类别同方向替换；另一类别不受影响
    db.replace_auto_trade_rates([_rate("chaos", "divine", 155.0)], db_path=path)
    default_rows = db.list_trade_rates(category="default", db_path=path)
    assert len(default_rows) == 1 and default_rows[0]["amount_to"] == 155.0
    assert len(db.list_trade_rates(category="custom", db_path=path)) == 1


def test_init_db_backfills_category(tmp_path) -> None:
    """旧库迁移：补 category 列，物品单位记录回填为 custom，其余为 default。"""
    import sqlite3

    path = tmp_path / "eco.db"
    with sqlite3.connect(path) as conn:
        conn.execute(
            "CREATE TABLE trade_rates ("
            " id INTEGER PRIMARY KEY AUTOINCREMENT,"
            " from_unit TEXT NOT NULL, to_unit TEXT NOT NULL,"
            " amount_from REAL NOT NULL, amount_to REAL NOT NULL,"
            " side TEXT NOT NULL DEFAULT 'sell',"
            " source TEXT NOT NULL DEFAULT 'manual', created_at TEXT NOT NULL)")
        conn.execute(
            "INSERT INTO trade_rates(from_unit, to_unit, amount_from, amount_to, side,"
            " source, created_at) VALUES ('chaos', 'divine', 1, 150, 'buy', 'auto', 't')")
        conn.execute(
            "INSERT INTO trade_rates(from_unit, to_unit, amount_from, amount_to, side,"
            " source, created_at) VALUES ('item:X', 'chaos', 1, 3, 'buy', 'auto', 't')")

    db.init_db(path)

    by_from = {r["from_unit"]: r for r in db.list_trade_rates(db_path=path)}
    assert by_from["chaos"]["category"] == "default"
    assert by_from["item:X"]["category"] == "custom"


# ============================================================
# 自动套利：通货对与抓取一致性复核
# ============================================================
def test_auto_pairs_multiple_dedup_and_skip_default() -> None:
    """多个通货 × 三默认；重名/空名/与默认通货同名者跳过。"""
    pairs = auto_pairs([
        "Orb of Annulment", "Orb of Chance",
        "Orb of Annulment",  # 重复
        "Divine Orb",        # 默认通货自身
        "  ",                # 空名
    ])
    assert len(pairs) == 6  # 2 个有效通货 × 3 默认
    units = {(p[0], p[2]) for p in pairs}
    assert ("item:Orb of Annulment", "exalted") in units
    assert ("item:Orb of Annulment", "chaos") in units
    assert ("item:Orb of Annulment", "divine") in units
    assert ("item:Orb of Chance", "divine") in units
    assert all(p[1] in ("Orb of Annulment", "Orb of Chance") for p in pairs)


def test_auto_pairs_empty() -> None:
    assert auto_pairs([]) == []


def test_check_scan_consistency_normal() -> None:
    """双向买价乘积 < 1 且隐含价格接近（正常价差）：无警告。"""
    result = {
        "b_to_a": [{"rank": 1, "ratio": "1:155", "stock": 120}],
        "a_to_b": [{"rank": 1, "ratio": "150:1", "stock": 450}],
    }
    assert check_scan_consistency(result, "A ↔ B") == ([], [])


def test_check_scan_consistency_abnormal() -> None:
    """乘积 ≥ 1（自由套利窗口或小幅识别偏差）：提示级警告，不阻断。"""
    result = {
        "b_to_a": [{"rank": 1, "ratio": "1:100", "stock": None}],
        "a_to_b": [{"rank": 1, "ratio": "200:1", "stock": None}],
    }
    warnings, criticals = check_scan_consistency(result, "甲 ↔ 乙")
    assert len(warnings) == 1
    assert "甲 ↔ 乙" in warnings[0] and "≥ 1" in warnings[0]
    assert criticals == []


def test_check_scan_consistency_spread_critical() -> None:
    """双向隐含价格价差超上限（2470:1 被误识别为 1:1）：严重异常，应跳过发布。"""
    result = {
        "b_to_a": [{"rank": 1, "ratio": "1:1", "stock": 5}],     # OCR 误识别
        "a_to_b": [{"rank": 1, "ratio": "2470:1", "stock": 12}],
    }
    warnings, criticals = check_scan_consistency(result, "崇高 ↔ 完美混沌")
    assert warnings == []
    assert len(criticals) == 1
    assert "价差" in criticals[0] and "不发布" in criticals[0]


def test_check_scan_consistency_missing_direction() -> None:
    """某方向无挂单或比例无法解析时不做判断。"""
    assert check_scan_consistency({"b_to_a": [], "a_to_b": [{"ratio": "158:1"}]}) == ([], [])
    bad = {"b_to_a": [{"ratio": "坏"}], "a_to_b": [{"ratio": "158:1"}]}
    assert check_scan_consistency(bad) == ([], [])


def test_runner_collects_consistency_warnings() -> None:
    """提示级复核异常记入 summary["warnings"] 并写日志，不影响发布。"""
    scanner = FakeScanner({
        ("Exalted Orb", "Chaos Orb"): {
            "b_to_a": [{"rank": 1, "ratio": "1:100", "stock": 5}],
            "a_to_b": [{"rank": 1, "ratio": "200:1", "stock": 3}],
        },
    })
    logs: list[tuple[str, str]] = []
    runner = ExchangeScanRunner(
        scanner,
        logger=lambda msg, level: logs.append((msg, level)),
        publisher=lambda rates, category: len(rates),
    )
    summary = runner.run(default_pairs())
    assert len(summary["warnings"]) == 1
    assert "双向买价乘积" in summary["warnings"][0]
    assert summary["published"] == 2  # 提示级警告不阻断发布
    assert summary["skipped"] == 0
    assert any(level == "WARN" and "复核" in msg for msg, level in logs)


def test_runner_skips_spread_anomalous_pair() -> None:
    """严重价差异常（必有一方向误识别）：该对比例跳过不发布。"""
    scanner = FakeScanner({
        ("Exalted Orb", "Chaos Orb"): {
            "b_to_a": [{"rank": 1, "ratio": "1:1", "stock": 5}],     # 误识别
            "a_to_b": [{"rank": 1, "ratio": "2470:1", "stock": 3}],
        },
    })
    runner = ExchangeScanRunner(
        scanner,
        logger=lambda msg, level: None,
        publisher=lambda rates, category: len(rates),
    )
    summary = runner.run(default_pairs())
    assert summary["skipped"] == 1
    assert summary["published"] == 0  # 严重异常对不发布
    assert len(summary["warnings"]) == 1
    assert "不发布" in summary["warnings"][0]
