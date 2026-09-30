#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交易助手纯逻辑单元测试：最优兑换路径与套利环检测。"""

from web import trading


def rate(frm, to, af, at, side="sell"):
    return {"from_unit": frm, "to_unit": to,
            "amount_from": af, "amount_to": at, "side": side}


# ---------- 基础工具 ----------

def test_unit_label_base_and_item():
    assert trading.unit_label("divine") == "神圣石"
    assert trading.unit_label("chaos") == "混沌石"
    assert trading.unit_label("exalted") == "崇高石"
    assert trading.unit_label("item:机会石") == "机会石"


def test_edge_rate():
    assert trading.edge_rate(rate("divine", "chaos", 1, 300)) == 300
    assert trading.edge_rate(rate("chaos", "divine", 310, 1)) == 1 / 310


# ---------- 最优兑换路径 ----------

def test_best_conversion_direct():
    rates = [rate("divine", "chaos", 1, 300)]
    r, path = trading.best_conversion(rates, "divine", "chaos")
    assert r == 300
    assert len(path) == 1


def test_best_conversion_prefers_indirect():
    # 直接 1 神圣 = 300 混沌；绕行 神圣->崇高->混沌 = 20 * 16 = 320 更划算
    rates = [
        rate("divine", "chaos", 1, 300),
        rate("divine", "exalted", 1, 20),
        rate("exalted", "chaos", 1, 16),
    ]
    r, path = trading.best_conversion(rates, "divine", "chaos")
    assert r == 320
    assert [e["from_unit"] for e in path] == ["divine", "exalted"]


def test_best_conversion_via_item():
    # 神圣->物品->混沌 优于直接兑换
    rates = [
        rate("divine", "chaos", 1, 300),
        rate("divine", "item:机会石", 1, 2),
        rate("item:机会石", "chaos", 1, 170),
    ]
    r, path = trading.best_conversion(rates, "divine", "chaos")
    assert r == 340
    assert len(path) == 2


def test_best_conversion_no_path():
    rates = [rate("divine", "chaos", 1, 300)]
    r, path = trading.best_conversion(rates, "exalted", "divine")
    assert r is None and path is None


def test_best_conversion_same_unit():
    r, path = trading.best_conversion([], "chaos", "chaos")
    assert r == 1.0 and path == []


def test_best_conversion_ignores_profitable_cycle_inflation():
    # 存在套利环时，简单路径约束保证结果不会被环无限放大
    rates = [
        rate("divine", "chaos", 1, 300),
        rate("chaos", "divine", 100, 1),  # 环：1 神圣 -> 300 混沌 -> 3 神圣
        rate("chaos", "exalted", 15, 1),
    ]
    r, path = trading.best_conversion(rates, "divine", "exalted")
    assert r == 20  # 300/15，只能走一次
    assert [e["from_unit"] for e in path] == ["divine", "chaos"]


# ---------- 套利环检测 ----------

def test_find_profitable_cycles_detects_two_edge_cycle():
    rates = [
        rate("divine", "chaos", 1, 300),
        rate("chaos", "divine", 100, 1),  # 300/100 = 3 倍
    ]
    cycles = trading.find_profitable_cycles(rates)
    assert len(cycles) == 1
    assert abs(cycles[0]["rate"] - 3.0) < 1e-9


def test_find_profitable_cycles_three_edge_cycle_with_item():
    rates = [
        rate("divine", "item:机会石", 1, 2),
        rate("item:机会石", "chaos", 1, 170),
        rate("chaos", "divine", 300, 1),  # 2*170/300 ≈ 1.133
    ]
    cycles = trading.find_profitable_cycles(rates)
    assert len(cycles) == 1
    assert abs(cycles[0]["rate"] - 340 / 300) < 1e-9


def test_find_profitable_cycles_excludes_balanced():
    # 互为倒数的双向比例，乘积为 1，不算套利
    rates = [
        rate("divine", "chaos", 1, 300),
        rate("chaos", "divine", 300, 1),
    ]
    assert trading.find_profitable_cycles(rates) == []


def test_find_profitable_cycles_dedupes_rotations():
    # 同一个环从不同起点枚举只应出现一次
    rates = [
        rate("divine", "chaos", 1, 300),
        rate("chaos", "exalted", 15, 1),
        rate("exalted", "divine", 30, 1),  # 300/15/30 = 0.67 反向 1.5 倍
        rate("divine", "exalted", 1, 30),
        rate("exalted", "chaos", 1, 15),
        rate("chaos", "divine", 300, 1),
    ]
    cycles = trading.find_profitable_cycles(rates)
    keys = set()
    for c in cycles:
        units = tuple(p["from_unit"] for p in c["path"])
        assert units not in keys
        keys.add(units)
    assert any(abs(c["rate"] - 1.5) < 1e-9 for c in cycles)


def test_find_profitable_cycles_sorted_desc():
    rates = [
        rate("divine", "chaos", 1, 300),
        rate("chaos", "divine", 100, 1),          # 3 倍
        rate("exalted", "chaos", 1, 20),
        rate("chaos", "exalted", 10, 1),          # 2 倍
    ]
    cycles = trading.find_profitable_cycles(rates)
    rates_found = [c["rate"] for c in cycles]
    assert rates_found == sorted(rates_found, reverse=True)


# ---------- 金币费（Currency Exchange 值） ----------

GV = {"exalted": 1000, "chaos": 50, "divine": 2500}  # 金币/个


def test_effective_rate_sell_unchanged():
    e = rate("divine", "chaos", 1, 300, "sell")
    assert trading.effective_rate(e, GV) == 300


def test_effective_rate_buy_deducts_gold_fee():
    # 买 1 神圣花 300 混沌 + 1×2500 金币 = 300 + 2500/50 = 350 混沌等值
    e = rate("chaos", "divine", 300, 1, "buy")
    assert abs(trading.effective_rate(e, GV) - (1 / 350)) < 1e-12


def test_effective_rate_buy_without_gold_values_falls_back():
    e = rate("chaos", "divine", 300, 1, "buy")
    assert trading.effective_rate(e, None) == 1 / 300
    assert trading.effective_rate(e, {}) == 1 / 300


def test_best_conversion_prefers_sell_over_fee_taxed_buy():
    # 同方向卖边 1:300 免费，买边 1:310 但需金币费（310 + 2500/50 = 360）
    rates = [
        rate("divine", "chaos", 1, 300, "sell"),
        rate("divine", "chaos", 1, 310, "buy"),
    ]
    r, path = trading.best_conversion(rates, "divine", "chaos", GV)
    assert r == 300
    assert path[0]["side"] == "sell"


def test_best_conversion_buy_path_uses_effective_rate():
    # 只有买边时按有效汇率计算：300 混沌买 1 神圣 + 2500 金币 → 1 神圣成本 350 混沌
    rates = [rate("chaos", "divine", 300, 1, "buy")]
    r, path = trading.best_conversion(rates, "chaos", "divine", GV)
    assert abs(r - 1 / 350) < 1e-12


def test_gold_conversion_basic():
    rates = [rate("divine", "chaos", 1, 300, "sell")]
    rows = {r["unit"]: r for r in trading.gold_conversion(rates, GV)}
    assert rows["chaos"]["gold_per_unit"] == 50
    assert rows["chaos"]["unit_per_gold"] == 1 / 50
    assert rows["chaos"]["chaos_per_gold"] == 1 / 50
    # 1 金币 = 1/2500 神圣 = (1/2500)*300 混沌 = 0.12 混沌
    assert abs(rows["divine"]["chaos_per_gold"] - 300 / 2500) < 1e-12


def test_gold_conversion_missing_ve():
    rows = {r["unit"]: r for r in trading.gold_conversion([], {"chaos": 50})}
    assert rows["divine"]["gold_per_unit"] is None
    assert rows["divine"]["chaos_per_gold"] is None
    assert rows["chaos"]["chaos_per_gold"] == 1 / 50


def test_cycle_with_buy_fee_not_profitable():
    # 无费看似套利：卖 1 神圣得 310 混沌，300 混沌即可买回 1 神圣
    # 但买回需 2500 金币 = 50 混沌等值（实际成本 350）→ 净亏
    rates = [
        rate("divine", "chaos", 1, 310, "sell"),
        rate("chaos", "divine", 300, 1, "buy"),
    ]
    assert trading.find_profitable_cycles(rates) != []
    assert trading.find_profitable_cycles(rates, GV) == []
