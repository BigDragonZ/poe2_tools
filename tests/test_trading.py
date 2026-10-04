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


def test_canon_item_name():
    assert trading.canon_item_name("Perfect Jeweller's Orb") == "perfectjewellersorb"
    assert trading.canon_item_name("Perfect Jewellers Orb") == "perfectjewellersorb"
    assert trading.canon_item_name("Orb of Annulment") == "orbofannulment"


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


# ---------- 最优套利方案 ----------

def test_find_cycles_no_filter_includes_losing():
    rates = [
        rate("divine", "chaos", 1, 300, "sell"),
        rate("chaos", "divine", 310, 1, "buy"),  # 300/310 < 1，亏损环
    ]
    assert trading.find_profitable_cycles(rates) == []
    cycles = trading.find_profitable_cycles(rates, min_profit=None)
    assert len(cycles) == 1
    assert abs(cycles[0]["rate"] - 300 / 310) < 1e-9


def test_cycle_plan_two_edge_buy_fees():
    # 1 神圣 -(卖)-> 310 混沌 -(买 300:1)-> 31/30 神圣
    # 买边金币费 = 31/30 × 2500
    rates = [
        rate("divine", "chaos", 1, 310, "sell"),
        rate("chaos", "divine", 300, 1, "buy"),
    ]
    cycle = trading.find_profitable_cycles(rates, min_profit=None)[0]
    # 环可从任一节点起枚举；统一旋到 divine 起点验证
    plan = trading.cycle_plan(cycle, GV)
    if plan["start_unit"] != "divine":
        path = cycle["path"]
        i = [p["from_unit"] for p in path].index("divine")
        plan = trading.cycle_plan({"path": path[i:] + path[:i]}, GV)
    assert plan["start_unit"] == "divine"
    s1, s2 = plan["steps"]
    assert s1["side"] == "sell" and s1["pay"] == 1 and s1["receive"] == 310
    assert s1["gold_fee"] is None
    assert s2["side"] == "buy" and s2["pay"] == 310
    assert abs(s2["receive"] - 310 / 300) < 1e-9
    assert abs(s2["gold_fee"] - (310 / 300) * 2500) < 1e-6
    assert abs(plan["total_gold_fee"] - (310 / 300) * 2500) < 1e-6
    assert abs(plan["final_amount"] - 310 / 300) < 1e-9
    # 金币费是消耗不是亏损：收益只看通货差价 +1/30
    assert abs(plan["profit_units"] - 1 / 30) < 1e-9
    assert plan["profitable"] is True
    # 金币效率：(1/30) / ((31/30)×2500) × 10000
    assert abs(plan["units_per_10k_gold"] - (1 / 30) / ((310 / 300) * 2500) * 10000) < 1e-9


def test_cycle_plan_unknown_ve_total_gold_none():
    rates = [
        rate("divine", "chaos", 1, 300),
        rate("chaos", "divine", 100, 1, "buy"),
    ]
    cycle = trading.find_profitable_cycles(rates)[0]
    plan = trading.cycle_plan(cycle, {"chaos": 50})  # 缺 divine 的 VE
    assert plan["total_gold_fee"] is None
    assert plan["units_per_10k_gold"] is None
    buy_step = [s for s in plan["steps"] if s["side"] == "buy"][0]
    assert buy_step["gold_fee"] is None


def test_best_arbitrage_picks_highest_rate_cycle():
    rates = [
        rate("divine", "chaos", 1, 300),
        rate("chaos", "divine", 100, 1),          # 环1：3 倍
        rate("exalted", "chaos", 1, 20),
        rate("chaos", "exalted", 10, 1),          # 环2：2 倍
    ]
    plan = trading.best_arbitrage(rates)
    assert plan["profitable"] is True
    assert abs(plan["rate"] - 3.0) < 1e-9
    assert {s["from_unit"] for s in plan["steps"]} == {"divine", "chaos"}
    assert abs(plan["final_amount"] - 3.0) < 1e-9
    assert abs(plan["profit_units"] - 2.0) < 1e-9


def test_best_arbitrage_gold_fee_not_deducted_from_profit():
    # 环1：差价 +3%，买边金币费高；环2：差价 +2%，无金币费
    # 目标是消耗金币换通货：按通货差价排序，环1 胜出，金币费不影响盈利判断
    rates = [
        rate("divine", "chaos", 1, 309, "sell"),
        rate("chaos", "divine", 300, 1, "buy"),
        rate("exalted", "chaos", 1, 20.4, "sell"),
        rate("chaos", "exalted", 20, 1, "sell"),
    ]
    plan = trading.best_arbitrage(rates, GV)
    assert plan["profitable"] is True
    assert {s["from_unit"] for s in plan["steps"]} == {"divine", "chaos"}
    assert abs(plan["profit_units"] - 0.03) < 1e-9


def test_best_arbitrage_picks_best_rotation():
    # 同一环差价收益相同，取金币费最低的起点旋转：
    # 从混沌起步（神圣腿交易量小、费 2500/300 ≈ 8.3）优于从神圣起步（费 ≈ 2575）
    rates = [
        rate("divine", "chaos", 1, 309, "sell"),
        rate("chaos", "divine", 300, 1, "buy"),
    ]
    plan = trading.best_arbitrage(rates, GV)
    assert plan["start_unit"] == "chaos"
    assert abs(plan["total_gold_fee"] - 2500 / 300) < 1e-6
    assert abs(plan["profit_units"] - 0.03) < 1e-9
    assert plan["profitable"] is True


def test_best_arbitrage_unprofitable_reference():
    # 无盈利环时仍返回最接近的环（profitable=False）
    rates = [
        rate("divine", "chaos", 1, 300, "sell"),
        rate("chaos", "divine", 310, 1, "buy"),
    ]
    plan = trading.best_arbitrage(rates)
    assert plan is not None and plan["profitable"] is False
    assert plan["rate"] < 1.0


def test_best_arbitrage_no_cycle_returns_none():
    rates = [rate("divine", "chaos", 1, 300)]
    assert trading.best_arbitrage(rates) is None
    assert trading.best_arbitrage([]) is None


# ---------- 自动套利：候选筛选 ----------

def _snap(slug, name_en, price_divine, price_chaos, name_zh="某通货", wiki_slug=None):
    return {"slug": slug, "name_en": name_en, "name_zh": name_zh,
            "price_divine": price_divine, "price_chaos": price_chaos,
            "wiki_slug": wiki_slug}


def test_filter_currency_candidates_range_boundary_and_sort():
    rows = [
        _snap("a", "Orb A", 0.5, 5.0),          # 下限边界：包含
        _snap("b", "Orb B", 20.0, 200.0),       # 上限边界：包含
        _snap("c", "Orb C", 20.01, None),       # 超上限：排除
        _snap("d", "Orb D", 0.49, None),        # 低于下限：排除
        _snap("divine", "Divine Orb", 1.0, 9.44),   # 默认通货自身：排除
        _snap("exalted", "Exalted Orb", 0.6, 6.0),  # 默认通货自身：排除
        _snap("chaos", "Chaos Orb", 0.1, 1.0),      # 默认通货自身：排除
        _snap("gold", "Gold", 0.001, 0.01),         # 金币自身：排除
    ]
    got = trading.filter_currency_candidates(rows, 9.44)
    assert [c["slug"] for c in got] == ["b", "a"]  # 按神圣价值降序


def test_filter_currency_candidates_chaos_fallback():
    # price_divine 缺失时用 price_chaos / chaos_per_divine 补齐
    rows = [_snap("x", "Orb X", None, 94.4)]
    got = trading.filter_currency_candidates(rows, 9.44)
    assert len(got) == 1
    assert abs(got[0]["price_divine"] - 10.0) < 1e-9
    # 两者皆缺：跳过
    rows = [_snap("y", "Orb Y", None, None)]
    assert trading.filter_currency_candidates(rows, 9.44) == []


def test_filter_currency_candidates_name_fallback():
    # name_en 缺失时由 wiki_slug 转换；连 wiki_slug 也没有则跳过（无法在市场搜索）
    rows = [
        _snap("annul", None, 2.0, 20.0, wiki_slug="Orb_of_Annulment"),
        _snap("noname", None, 2.0, 20.0),
    ]
    got = trading.filter_currency_candidates(rows, 10.0)
    assert len(got) == 1
    assert got[0]["name_en"] == "Orb of Annulment"


def test_filter_currency_candidates_custom_range():
    rows = [_snap("a", "Orb A", 3.0, 30.0), _snap("b", "Orb B", 8.0, 80.0)]
    got = trading.filter_currency_candidates(rows, 10.0, lo=5.0, hi=10.0)
    assert [c["slug"] for c in got] == ["b"]


# ---------- 自动套利：金币获取方案 ----------

def test_best_gold_plans_best_and_alternatives():
    rates = [
        rate("divine", "chaos", 1, 310, "buy"),   # 直换：50 金币/混沌（= VE(chaos)）
        rate("exalted", "chaos", 1, 19, "sell"),  # 卖出免金币：0 金币/混沌
        rate("divine", "exalted", 1, 15, "buy"),
        rate("chaos", "divine", 300, 1, "buy"),
    ]
    plans = {p["target"]: p for p in trading.best_gold_plans(rates, GV)}
    chaos = plans["chaos"]
    assert chaos["best"]["source"] == "exalted"  # 免金币路径胜出
    assert chaos["best"]["gold_per_unit"] == 0
    assert chaos["best"]["final_amount"] == 19
    assert any(a["source"] == "divine" for a in chaos["alternatives"])
    divine = plans["divine"]
    assert divine["best"]["source"] == "chaos"
    # 1 混沌 → 1/300 神圣，金币费 (1/300)×2500；折合每 1 神圣 = 2500 金币（= VE(divine)）
    assert abs(divine["best"]["gold_per_unit"] - 2500) < 1e-6


def test_best_gold_plans_item_source_and_two_edge_fee():
    # 绕行 崇高→物品→混沌 的金币费含两段（物品段 VE(item) + 混沌段 VE(chaos)），贵于直换
    rates = [
        rate("divine", "chaos", 1, 310, "buy"),
        rate("exalted", "item:机会石", 1, 2, "buy"),
        rate("item:机会石", "chaos", 1, 170, "buy"),
    ]
    gv = dict(GV)
    gv["item:机会石"] = 100
    plans = {p["target"]: p for p in trading.best_gold_plans(rates, gv)}
    chaos = plans["chaos"]
    assert chaos["best"]["source"] == "divine"
    assert len(chaos["best"]["path"]) == 1
    assert abs(chaos["best"]["gold_per_unit"] - 50) < 1e-9
    via_item = [a for a in chaos["alternatives"] if len(a["path"]) == 2][0]
    assert via_item["source"] == "exalted"
    # 1 崇高 → 2 机会石（费 2×100）→ 340 混沌（费 340×50），共 17200 / 340 ≈ 50.59
    assert abs(via_item["gold_per_unit"] - (200 + 17000) / 340) < 1e-9
    assert via_item["gold_fee"] == 200 + 17000


def test_best_gold_plans_unknown_target_ve_gives_none():
    # 目标通货 VE 缺失：买边金币费未知 → gold_per_unit 为 None，仍给出路径
    rates = [rate("divine", "chaos", 1, 310, "buy")]
    plans = {p["target"]: p for p in trading.best_gold_plans(rates, {"divine": 2500})}
    chaos = plans["chaos"]
    assert chaos["best"] is not None
    assert chaos["best"]["gold_fee"] is None
    assert chaos["best"]["gold_per_unit"] is None


def test_best_gold_plans_no_path():
    plans = {p["target"]: p for p in trading.best_gold_plans([], GV)}
    for p in plans.values():
        assert p["best"] is None and p["alternatives"] == []


# ---------- 自动套利：方案复核（double check） ----------

def test_verify_arbitrage_plan_ok():
    rates = [
        rate("divine", "chaos", 1, 310, "sell"),
        rate("chaos", "divine", 300, 1, "buy"),
    ]
    plan = trading.best_arbitrage(rates, GV)
    check = trading.verify_arbitrage_plan(rates, GV, plan)
    assert check["ok"] is True
    assert check["discrepancies"] == []
    assert abs(check["expected_final"] - plan["final_amount"]) < 1e-9
    assert abs(check["expected_gold"] - plan["total_gold_fee"]) < 1e-6


def test_verify_arbitrage_plan_detects_tampered_final():
    rates = [
        rate("divine", "chaos", 1, 310, "sell"),
        rate("chaos", "divine", 300, 1, "buy"),
    ]
    plan = trading.best_arbitrage(rates, GV)
    tampered = dict(plan)
    tampered["final_amount"] = plan["final_amount"] * 1.01
    check = trading.verify_arbitrage_plan(rates, GV, tampered)
    assert check["ok"] is False
    assert any("终值" in d for d in check["discrepancies"])


def test_verify_arbitrage_plan_detects_missing_edge():
    rates = [
        rate("divine", "chaos", 1, 310, "sell"),
        rate("chaos", "divine", 300, 1, "buy"),
    ]
    plan = trading.best_arbitrage(rates, GV)
    first = plan["path"][0]
    reduced = [r for r in rates
               if not (r["from_unit"] == first["from_unit"]
                       and r["to_unit"] == first["to_unit"])]
    check = trading.verify_arbitrage_plan(reduced, GV, plan)
    assert check["ok"] is False
    assert any("找不到" in d for d in check["discrepancies"])


def test_verify_arbitrage_plan_without_path():
    check = trading.verify_arbitrage_plan([], GV, {"final_amount": 1.0})
    assert check["ok"] is False
    assert any("路径" in d for d in check["discrepancies"])


# ---------- 套利方案持仓优化（神圣口径） ----------

# 环 A：神圣 -(卖 1:309)-> 混沌 -(买 300:1)-> 神圣（1.03 倍）
# 环 B：神圣 -(买 1:2)-> 机会石 -(买 1:170)-> 混沌 -(买 300:1)-> 神圣（340/300 ≈ 1.133 倍）
ARB_RATES = [
    rate("divine", "chaos", 1, 309, "sell"),
    rate("chaos", "divine", 300, 1, "buy"),
    rate("divine", "item:机会石", 1, 2, "buy"),
    rate("item:机会石", "chaos", 1, 170, "buy"),
]
ARB_GV = {"divine": 2500, "chaos": 50, "exalted": 1000, "item:机会石": 100}


def test_arbitrage_opportunities_enumerates_cycles_and_rotations():
    opps = trading.arbitrage_opportunities(ARB_RATES, ARB_GV)
    assert len(opps) == 5  # 环 A 2 旋转 + 环 B 3 旋转
    # 按每万金币净得（神圣当量）降序：环 A 混沌起点（费最低）居首
    first = opps[0]
    assert first["start_unit"] == "chaos"
    assert abs(first["rate"] - 1.03) < 1e-9
    assert abs(first["total_gold_fee"] - 2500 / 300) < 1e-9
    # 混沌折神圣 = best_conversion 原始汇率 1/300
    assert abs(first["divine_value"] - 1 / 300) < 1e-9
    assert abs(first["profit_divine_per_loop"] - 0.03 / 300) < 1e-12
    assert abs(first["divine_per_10k_gold"] - 0.12) < 1e-9
    effs = [o["divine_per_10k_gold"] for o in opps]
    assert effs == sorted(effs, reverse=True)
    # 环 B 物品起点：divine_value 经物品→混沌→神圣最优路径折算（170/300）
    item_opp = [o for o in opps if o["start_unit"] == "item:机会石"][0]
    assert abs(item_opp["divine_value"] - 170 / 300) < 1e-9
    assert abs(item_opp["profit_units"] - (340 / 300 - 1)) < 1e-9
    assert abs(item_opp["profit_divine_per_loop"] - (340 / 300 - 1) * 170 / 300) < 1e-9


def test_arbitrage_opportunities_skips_unknown_ve():
    # 缺 item:机会石 的 VE：环 B 每个旋转都含物品买边（费 None）→ 整条环跳过
    gv = {"divine": 2500, "chaos": 50}
    opps = trading.arbitrage_opportunities(ARB_RATES, gv)
    assert len(opps) == 2
    assert {o["start_unit"] for o in opps} == {"divine", "chaos"}


def test_best_arbitrage_plan_math():
    """持仓 神圣167/混沌207/金币750万：最优为环 A 混沌起点（手算对照）。

    每环（1 混沌口径）：费 2500/300 金币，净得 0.03 混沌；
    batch=min(207, 7500000/(2500/300)) = 207 → 每环费 1725 金币，
    loops=7500000/1725；profit_total = 0.03×7500000/(2500/300) = 27000 混沌；
    total_gold_fee = 1725×loops = 7500000（不超预算）；
    final = 207+27000 = 27207 混沌，折神圣 27207/300 = 90.69。
    """
    holdings = {"divine": 167, "chaos": 207, "gold": 7500000}
    plan = trading.best_arbitrage_plan(ARB_RATES, ARB_GV, holdings)
    assert plan["start_unit"] == "chaos"
    assert plan["principal"] == 207
    assert plan["batch"] == 207
    assert plan["gold_budget"] == 7500000
    assert abs(plan["loops"] - 7500000 / ((2500 / 300) * 207)) < 1e-9
    assert abs(plan["profit_total"] - 27000) < 1e-6
    assert abs(plan["total_gold_fee"] - 7500000) < 1e-3  # 消耗金币不超预算
    assert plan["total_gold_fee"] <= plan["gold_budget"]
    assert abs(plan["final_amount"] - 27207) < 1e-6
    assert abs(plan["final_divine"] - 27207 / 300) < 1e-9
    # 执行步骤按 batch 缩放（207 混沌 → 0.69 神圣 → 213.21 混沌）
    s1, s2 = plan["steps"]
    assert s1["from_unit"] == "chaos" and s1["side"] == "buy"
    assert abs(s1["pay"] - 207) < 1e-9
    assert abs(s1["receive"] - 207 / 300) < 1e-9
    assert abs(s1["gold_fee"] - (207 / 300) * 2500) < 1e-6
    assert s2["from_unit"] == "divine" and s2["side"] == "sell"
    assert s2["gold_fee"] is None
    assert abs(s2["receive"] - (207 / 300) * 309) < 1e-6
    # double check：1 本金口径独立复核一致
    assert plan["check"]["ok"] is True


def test_best_arbitrage_plan_skips_zero_holding():
    """混沌持仓为 0：混沌起点的条目跳过，最优退为环 A 神圣起点。"""
    holdings = {"divine": 167, "chaos": 0, "gold": 7500000}
    plan = trading.best_arbitrage_plan(ARB_RATES, ARB_GV, holdings)
    assert plan["start_unit"] == "divine"
    assert plan["batch"] == 167
    # profit_total = 0.03 × 7500000 / 2575（batch 抵消）
    assert abs(plan["profit_total"] - 0.03 * 7500000 / 2575) < 1e-6
    assert abs(plan["final_amount"] - (167 + plan["profit_total"])) < 1e-9
    assert abs(plan["final_divine"] - plan["final_amount"]) < 1e-9  # 神圣起点折神圣系数 1


def test_best_arbitrage_plan_batch_capped_by_gold_budget():
    """金币预算跑不满整仓一环：每环本金按预算缩减，消耗金币不超预算。

    环 A 混沌起点：fee_per_unit = 2500/300 ≈ 8.33；持仓 207 混沌整仓一环需
    1725 金币，预算只有 1000 → batch = 1000/(2500/300) = 120 混沌，loops = 1，
    total_gold_fee = 1000 = 预算，profit_total = 0.03 × 120 = 3.6 混沌。
    """
    holdings = {"divine": 167, "chaos": 207, "gold": 1000}
    plan = trading.best_arbitrage_plan(ARB_RATES, ARB_GV, holdings)
    assert plan["start_unit"] == "chaos"
    assert plan["principal"] == 207
    assert abs(plan["batch"] - 120) < 1e-9
    assert abs(plan["loops"] - 1.0) < 1e-9
    assert abs(plan["total_gold_fee"] - 1000) < 1e-6
    assert plan["total_gold_fee"] <= plan["gold_budget"]
    assert abs(plan["profit_total"] - 3.6) < 1e-6
    assert abs(plan["final_amount"] - 210.6) < 1e-6
    # 步骤按缩减后的每环本金缩放
    assert abs(plan["steps"][0]["pay"] - 120) < 1e-9


def test_best_arbitrage_plan_accepts_exalted_principal():
    """崇高石同样可作为套利本金（PRINCIPAL_UNITS）。"""
    rates = [
        rate("exalted", "chaos", 60, 1, "buy"),   # 买 1 混沌费 1×50 金币
        rate("chaos", "exalted", 1, 62, "sell"),  # 环收益 62/60
        rate("chaos", "divine", 300, 1, "buy"),   # 崇高折神圣的路径
        rate("divine", "chaos", 1, 300, "buy"),
    ]
    gv = {"chaos": 50, "exalted": 1000, "divine": 2500}
    holdings = {"divine": 0, "chaos": 0, "exalted": 600, "gold": 100000}
    plan = trading.best_arbitrage_plan(rates, gv, holdings)
    assert plan["start_unit"] == "exalted"
    assert plan["batch"] == 600
    assert plan["total_gold_fee"] <= holdings["gold"]
    assert plan["profit_total"] > 0


def test_best_arbitrage_plan_none():
    # 两种本金持仓都为 0
    assert trading.best_arbitrage_plan(
        ARB_RATES, ARB_GV, {"divine": 0, "chaos": 0, "gold": 7500000}) is None
    # 金币预算为 0：无法支付买边金币费，无可执行方案
    assert trading.best_arbitrage_plan(
        ARB_RATES, ARB_GV, {"divine": 167, "chaos": 207, "gold": 0}) is None
    # 无盈利环（互为倒数的平衡比例）
    balanced = [rate("divine", "chaos", 1, 300), rate("chaos", "divine", 300, 1)]
    assert trading.best_arbitrage_plan(
        balanced, ARB_GV, {"divine": 167, "chaos": 207, "gold": 7500000}) is None
