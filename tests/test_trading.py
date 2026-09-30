#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交易助手纯逻辑单元测试：最优兑换路径与套利环检测。"""

from web import trading


def rate(frm, to, af, at):
    return {"from_unit": frm, "to_unit": to, "amount_from": af, "amount_to": at}


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
