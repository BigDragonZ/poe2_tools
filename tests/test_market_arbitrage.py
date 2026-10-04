#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""自动套利抓取编排：候选加载（临时库）、金币消耗检查与批量抓取汇总。"""

from __future__ import annotations

import pytest

from poe2_tools.modules.market import arbitrage
from poe2_tools.modules.market.arbitrage import (
    ArbitrageDataError,
    ArbitrageScanRunner,
    candidates_missing_gold_costs,
    load_candidates,
)
from web import db


def _seed_currency_db(path) -> None:
    """造一个含通货快照的临时库：默认通货 + 各价位候选 + 超范围通货。"""
    db.init_db(path)
    season_id = db.create_season("0.5.5闪回", "2026-09-01", db_path=path)
    db.upsert_module("Economy_Currency", "通货", db_path=path)
    module = db.get_module_by_slug("Economy_Currency", db_path=path)
    items = [
        ("divine", "神圣石", "Divine Orb", 1.0, 9.44),
        ("chaos", "混沌石", "Chaos Orb", 1 / 9.44, 1.0),
        ("exalted", "崇高石", "Exalted Orb", 0.3, 3.0),       # 低于默认下限 + 默认通货
        ("annul", "废止之珠", "Orb of Annulment", 2.0, 18.88),
        ("chance", "机会石", "Orb of Chance", None, 47.2),     # 缺 price_divine，chaos 补齐 = 5
        ("mirror", "卡兰德的魔镜", "Mirror of Kalandra", 500.0, 4720.0),  # 超上限
    ]
    for slug, name_zh, name_en, price_divine, price_chaos in items:
        item_id = db.upsert_item(module["id"], slug, name_zh, name_en, None, None,
                                 db_path=path)
        db.insert_snapshot(item_id, season_id, "2026-10-04T10:00:00",
                           {"price_divine": price_divine, "price_chaos": price_chaos},
                           db_path=path)
    db.set_setting("chaos_per_divine", "9.44", db_path=path)


def test_load_candidates_no_snapshots(tmp_path) -> None:
    """无快照数据：抛出中文提示（先在 Web 端刷新经济数据）。"""
    path = tmp_path / "eco.db"
    db.init_db(path)
    with pytest.raises(ArbitrageDataError, match="刷新"):
        load_candidates(db_path=path)


def test_load_candidates_filters_and_fills(tmp_path) -> None:
    """按区间筛选、排除默认通货、price_divine 缺失用 chaos 补齐、按价值降序。"""
    path = tmp_path / "eco.db"
    _seed_currency_db(path)
    candidates = load_candidates(db_path=path)
    assert [c["name_en"] for c in candidates] == ["Orb of Chance", "Orb of Annulment"]
    assert abs(candidates[0]["price_divine"] - 5.0) < 1e-9
    assert candidates[1]["price_divine"] == 2.0


def test_load_candidates_empty_range_raises(tmp_path) -> None:
    """区间内无候选：抛出中文提示。"""
    path = tmp_path / "eco.db"
    _seed_currency_db(path)
    with pytest.raises(ArbitrageDataError, match="没有候选"):
        load_candidates(lo=100.0, hi=200.0, db_path=path)


def test_candidates_missing_gold_costs(tmp_path) -> None:
    """item_info 中有金币消耗的不算缺失；names=None 时返回全部。"""
    path = tmp_path / "eco.db"
    _seed_currency_db(path)
    annul_item = [it for it in db.list_library_items(db_path=path)
                  if it["slug"] == "annul"][0]
    db.upsert_item_info(annul_item["item_id"], None, 123.0, "废止之珠",
                        "Orb of Annulment", db_path=path)
    candidates = [{"name_en": "Orb of Annulment"}, {"name_en": "Orb of Chance"}]
    assert candidates_missing_gold_costs(candidates, db_path=path) == ["Orb of Chance"]
    assert db.get_gold_costs_by_names_en(db_path=path) == {"Orb of Annulment": 123.0}
    assert db.get_gold_costs_by_names_en(["Orb of Annulment"], db_path=path) == {
        "Orb of Annulment": 123.0}


def test_candidates_missing_gold_costs_canon_match(tmp_path) -> None:
    """撇号等标点差异不算缺失：wiki 名 Perfect Jeweller's Orb ↔ 游戏内搜索名
    Perfect Jewellers Orb 按归一化名称匹配。"""
    path = tmp_path / "eco.db"
    _seed_currency_db(path)
    annul_item = [it for it in db.list_library_items(db_path=path)
                  if it["slug"] == "annul"][0]
    db.upsert_item_info(annul_item["item_id"], None, 1000.0, "完美工匠石",
                        "Perfect Jeweller's Orb", db_path=path)
    candidates = [{"name_en": "Perfect Jewellers Orb"}, {"name_en": "Orb of Chance"}]
    assert candidates_missing_gold_costs(candidates, db_path=path) == ["Orb of Chance"]


def test_load_candidates_corrects_name_from_wiki(tmp_path) -> None:
    """快照 name_en 由 wiki_slug 转换丢撇号：候选名用信息库 wiki BaseType 名纠正
    （Perfect Jewellers Orb → Perfect Jeweller's Orb）。"""
    path = tmp_path / "eco.db"
    _seed_currency_db(path)
    annul_item = [it for it in db.list_library_items(db_path=path)
                  if it["slug"] == "annul"][0]
    db.upsert_item_info(annul_item["item_id"], None, 400.0, "废止之珠",
                        "Orb of An'nulment", db_path=path)
    candidates = load_candidates(db_path=path)
    names = [c["name_en"] for c in candidates]
    assert "Orb of An'nulment" in names
    assert "Orb of Annulment" not in names


class FakeScanner:
    """固定返回同一抓取结果的假扫描器。"""

    def __init__(self, result: dict) -> None:
        self._result = result
        self.calls: list[tuple[str, str]] = []

    def preflight(self) -> None:
        pass

    def scan(self, currency_a: str, currency_b: str) -> dict:
        self.calls.append((currency_a, currency_b))
        return self._result


def test_runner_publishes_auto_category(tmp_path, monkeypatch) -> None:
    """候选 × 三默认批量抓取 → category=auto 发布；缺 VE 警告并入 warnings。"""
    candidates = [
        {"slug": "annul", "name_en": "Orb of Annulment", "name_zh": "废止之珠",
         "price_divine": 2.0, "price_chaos": 18.88},
    ]
    monkeypatch.setattr(arbitrage, "load_candidates",
                        lambda lo, hi, db_path=None: candidates)
    monkeypatch.setattr(arbitrage, "candidates_missing_gold_costs",
                        lambda c, db_path=None: ["Orb of Annulment"])
    published: list[tuple[str, list[dict]]] = []
    scanner = FakeScanner({
        "b_to_a": [{"rank": 1, "ratio": "1:10", "stock": 5}],
        "a_to_b": [{"rank": 1, "ratio": "9:1", "stock": 3}],
    })
    runner = ArbitrageScanRunner(
        scanner, publisher=lambda rates, category: published.append((category, rates))
        or len(rates))

    summary = runner.run()

    assert summary["category"] == "auto"
    assert summary["pairs"] == 3
    assert len(scanner.calls) == 3
    assert published[0][0] == "auto"
    assert summary["candidates"] == candidates
    assert summary["missing_gold_costs"] == ["Orb of Annulment"]
    assert any("Currency Exchange" in w for w in summary["warnings"])
    # 比例一致（买价乘积 0.9 < 1）：无复核警告
    assert not any("复核" in w or "乘积" in w for w in summary["warnings"])


# ============================================================
# 单位双名：英文名 → 中文名映射（items 与 item_info 合并，归一化匹配）
# ============================================================
def test_get_names_zh_by_names_en(tmp_path) -> None:
    """items 模块页名优先于 item_info wiki 名；撇号名归一化后可匹配。"""
    from web import trading

    path = tmp_path / "eco.db"
    _seed_currency_db(path)
    annul_item = [it for it in db.list_library_items(db_path=path)
                  if it["slug"] == "annul"][0]
    db.upsert_item_info(annul_item["item_id"], None, 100.0, "废止之珠·wiki",
                        "Orb of Annulment", db_path=path)
    names = db.get_names_zh_by_names_en(db_path=path)
    assert names["Orb of Annulment"] == "废止之珠"  # items 名覆盖 item_info 名
    assert names["Orb of Chance"] == "机会石"
    # 信息库 BaseType 名带撇号，游戏内搜索名不带 → canon_item_name 归一化匹配
    chance_item = [it for it in db.list_library_items(db_path=path)
                   if it["slug"] == "chance"][0]
    db.upsert_item_info(chance_item["item_id"], None, 25.0, "机会石·wiki",
                        "Orb of Chance's", db_path=path)
    names = db.get_names_zh_by_names_en(db_path=path)
    canon = {trading.canon_item_name(n): zh for n, zh in names.items()}
    assert canon[trading.canon_item_name("Orb of Chances")] == "机会石·wiki"
