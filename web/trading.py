"""交易页纯逻辑：汇率图、最优兑换路径、套利环检测、最优套利方案展开、金币折算。

汇率以「边」表示：from_unit --(amount_from -> amount_to)--> to_unit。
基础通货 unit 固定为 exalted / chaos / divine，物品 unit 为 "item:名称"。
汇率数据由桌面端游玩工具的市场比例抓取同步入库（trade_rates.category 区分
默认/指定/自动页面），本模块只负责计算。

市场规则（用户确认的 POE2 金币交易模型）：
- 每条边分买（buy）/ 卖（sell）两侧；卖出不收金币。
- 买入的金币费 = 买入数量 × 买入通货的 Currency Exchange 值（VE，金币/个）。
- 因此 1 个通货 X ≡ VE(X) 金币，买边的有效汇率需把金币费折算成支付方通货。
"""

import math

BASE_CURRENCIES = ["exalted", "chaos", "divine"]

BASE_LABELS = {"exalted": "崇高石", "chaos": "混沌石", "divine": "神圣石"}

# 三种默认通货的游戏内英文全名（双名展示用）
BASE_NAMES_EN = {"exalted": "Exalted Orb", "chaos": "Chaos Orb", "divine": "Divine Orb"}

ITEM_PREFIX = "item:"


def item_unit(name):
    return ITEM_PREFIX + name


def is_item_unit(unit):
    return unit.startswith(ITEM_PREFIX)


def canon_item_name(name):
    """物品名归一化（小写、仅保留字母数字）：抹平信息库 wiki 名与游戏内
    搜索名的标点差异（如 Perfect Jeweller's Orb ↔ Perfect Jewellers Orb），
    供金币消耗（Currency Exchange 值）按名匹配时使用。"""
    return "".join(ch for ch in name.lower() if ch.isalnum())


def unit_label(unit):
    if unit in BASE_LABELS:
        return BASE_LABELS[unit]
    if is_item_unit(unit):
        return unit[len(ITEM_PREFIX):]
    return unit


def edge_rate(entry):
    """1 个 from_unit 可换多少个 to_unit。"""
    return entry["amount_to"] / entry["amount_from"]


def effective_rate(entry, gold_values=None):
    """考虑金币费后的有效汇率：1 个 from_unit 实际净得多少 to_unit。

    买边：每 1 from 换得 r to，付金币 r × VE(to)；金币按 1 from ≡ VE(from) 金币
    折算回 from，总成本 1 + r×VE(to)/VE(from) 个 from，故有效汇率 = r / (1 + r×VE(to)/VE(from))。
    卖边、物品边、缺 VE 时退化为原始汇率。
    """
    r = edge_rate(entry)
    if not gold_values or entry.get("side") != "buy":
        return r
    ve_to = gold_values.get(entry["to_unit"])
    ve_from = gold_values.get(entry["from_unit"])
    if not ve_to or not ve_from or ve_to <= 0 or ve_from <= 0:
        return r
    return r / (1 + r * ve_to / ve_from)


def gold_conversion(rates, gold_values):
    """金币 ⇄ 通货转化比例。

    每通货一行：gold_per_unit（= VE）、unit_per_gold（= 1/VE）、
    chaos_per_gold（1 金币经最优路径折合多少混沌）。
    """
    rows = []
    for u in BASE_CURRENCIES:
        ve = gold_values.get(u)
        if not ve or ve <= 0:
            rows.append({"unit": u, "gold_per_unit": None,
                         "unit_per_gold": None, "chaos_per_gold": None})
            continue
        unit_per_gold = 1.0 / ve
        chaos_per_gold = None
        rate, _ = best_conversion(rates, u, "chaos", gold_values)
        if rate:
            chaos_per_gold = unit_per_gold * rate
        rows.append({"unit": u, "gold_per_unit": ve,
                     "unit_per_gold": unit_per_gold, "chaos_per_gold": chaos_per_gold})
    return rows


def build_graph(rates):
    """from_unit -> [汇率记录...]。"""
    graph = {}
    for r in rates:
        graph.setdefault(r["from_unit"], []).append(r)
    return graph


def best_conversion(rates, src, dst, gold_values=None):
    """在汇率图中找 src -> dst 兑换率最高的简单路径（不重复节点，避免套利环无限放大）。

    提供 gold_values 时买边按有效汇率（扣除金币费）计算。
    返回 (rate, path)，path 为汇率记录列表；无路径时返回 (None, None)。
    """
    if src == dst:
        return 1.0, []
    graph = build_graph(rates)
    best_rate = 0.0
    best_path = None

    def dfs(node, acc, path, visited):
        nonlocal best_rate, best_path
        if node == dst:
            if acc > best_rate:
                best_rate = acc
                best_path = list(path)
            return
        for e in graph.get(node, []):
            nxt = e["to_unit"]
            if nxt in visited:
                continue
            visited.add(nxt)
            path.append(e)
            dfs(nxt, acc * effective_rate(e, gold_values), path, visited)
            path.pop()
            visited.discard(nxt)

    dfs(src, 1.0, [], {src})
    if best_path is None:
        return None, None
    return best_rate, best_path


def find_profitable_cycles(rates, gold_values=None, min_profit=1e-9):
    """枚举简单兑换环，按收益率（有效汇率乘积）降序返回 [{"rate", "path"}]。

    默认只保留乘积 > 1 + min_profit 的环（套利机会）；min_profit=None 时
    不过滤，返回全部环。同一环的旋转视为同一个环。
    """
    graph = build_graph(rates)
    found = {}

    def dfs(start, node, acc, path, visited):
        for e in graph.get(node, []):
            nxt = e["to_unit"]
            if nxt == start and path:
                cycle_path = path + [e]
                rate = acc * effective_rate(e, gold_values)
                if min_profit is None or rate > 1.0 + min_profit:
                    units = [p["from_unit"] for p in cycle_path]
                    key = min(tuple(units[i:] + units[:i]) for i in range(len(units)))
                    if key not in found or found[key]["rate"] < rate:
                        found[key] = {"rate": rate, "path": cycle_path}
            elif nxt not in visited:
                visited.add(nxt)
                dfs(start, nxt, acc * effective_rate(e, gold_values), path + [e], visited)
                visited.discard(nxt)

    for start in list(graph.keys()):
        dfs(start, start, 1.0, [], {start})
    return sorted(found.values(), key=lambda c: c["rate"], reverse=True)


def cycle_plan(cycle, gold_values=None):
    """把兑换环展开为以 1 个起点通货为基准的可执行步骤明细。

    执行模型（用户持有金币与通货，目标是消耗金币兑换通货）：每步按原始
    市场比例兑换，买边金币费以金币实付（receive × VE(to)，VE 未知时为
    None）。金币费是套利的正常消耗而非亏损，不计入收益——收益只看通货
    差价：profit_units = 环终值 - 1（起点通货计）。
    返回 {"start_unit", "steps", "final_amount", "rate", "profit_units",
    "total_gold_fee", "units_per_10k_gold", "profitable"}；
    units_per_10k_gold 为金币效率（每 1 万金币净得多少起点通货），
    费用未知或为 0 时为 None。
    """
    path = cycle["path"]
    start_unit = path[0]["from_unit"]
    steps = []
    amount = 1.0
    total_gold = 0.0
    gold_known = True
    for e in path:
        r = edge_rate(e)
        received = amount * r
        fee = None
        if e.get("side") == "buy":
            ve = (gold_values or {}).get(e["to_unit"])
            if ve and ve > 0:
                fee = received * ve
                total_gold += fee
            else:
                gold_known = False
        steps.append({"from_unit": e["from_unit"], "to_unit": e["to_unit"],
                      "side": e.get("side", "sell"), "rate": r,
                      "amount_from": e["amount_from"], "amount_to": e["amount_to"],
                      "pay": amount, "receive": received, "gold_fee": fee})
        amount = received
    profit_units = amount - 1.0
    efficiency = None
    if gold_known and total_gold > 0:
        efficiency = profit_units / total_gold * 10000
    return {"start_unit": start_unit, "steps": steps,
            "final_amount": amount, "rate": amount,
            "profit_units": profit_units,
            "total_gold_fee": total_gold if gold_known else None,
            "units_per_10k_gold": efficiency,
            "profitable": profit_units > 0}


def best_arbitrage(rates, gold_values=None):
    """最优套利方案：全部简单环（含各起点旋转）中通货差价收益最高者。

    用户目标是消耗金币兑换通货：收益按通货差价（环终值 - 1，起点通货计）
    排序，金币费只是正常消耗、不影响盈利判断。环的每个旋转是不同的执行
    方式（各步交易量相对大小不同、金币费不同），同一环内取金币费最低的
    起点（同样差价收益下金币效率最高，同样预算可跑更多循环）。
    无环时返回 None；最高收益环差价不为正时照常返回（profitable=False，
    供参考差价距离）。
    """
    cycles = find_profitable_cycles(rates, gold_values, min_profit=None)
    if not cycles:
        return None
    best = None
    best_key = None
    for c in cycles:
        path = c["path"]
        for i in range(len(path)):
            rot = path[i:] + path[:i]
            plan = cycle_plan({"path": rot}, gold_values)
            key = (plan["final_amount"], -(plan["total_gold_fee"] or 0))
            if best_key is None or key > best_key:
                best_key = key
                best = plan
                best["path"] = rot
    return best


# ---------- 自动套利：候选筛选与金币获取方案 ----------

# 候选通货默认价值区间（神圣计）
DEFAULT_CANDIDATE_LO = 0.5
DEFAULT_CANDIDATE_HI = 20.0

# 候选集合排除的 slug：三种默认通货自身与金币（套利对象是非默认通货）
EXCLUDED_CANDIDATE_SLUGS = frozenset({"divine", "exalted", "chaos", "gold"})


def filter_currency_candidates(rows, chaos_per_divine, lo=DEFAULT_CANDIDATE_LO,
                               hi=DEFAULT_CANDIDATE_HI):
    """从通货模块快照行中筛选价值在 [lo, hi] 神圣之间的候选通货，按神圣价值降序。

    price_divine 缺失时用 price_chaos / chaos_per_divine 补齐，仍缺失则跳过；
    排除三种默认通货与金币自身；无游戏内英文名（无法在市场搜索）的跳过。
    返回 [{"slug", "name_en", "name_zh", "price_divine", "price_chaos"}]。
    """
    candidates = []
    for row in rows:
        slug = row.get("slug")
        if slug in EXCLUDED_CANDIDATE_SLUGS:
            continue
        price_divine = row.get("price_divine")
        price_chaos = row.get("price_chaos")
        if price_divine is None and price_chaos and chaos_per_divine:
            price_divine = price_chaos / chaos_per_divine
        if price_divine is None or not (lo <= price_divine <= hi):
            continue
        name_en = row.get("name_en")
        if not name_en and row.get("wiki_slug"):
            name_en = row["wiki_slug"].replace("_", " ")
        if not name_en:
            continue
        if price_chaos is None and chaos_per_divine:
            price_chaos = price_divine * chaos_per_divine
        candidates.append({
            "slug": slug,
            "name_en": name_en,
            "name_zh": row.get("name_zh"),
            "price_divine": price_divine,
            "price_chaos": price_chaos,
        })
    candidates.sort(key=lambda c: c["price_divine"], reverse=True)
    return candidates


def gold_unit_cost(path, gold_values):
    """沿兑换路径换算「消耗金币口径」下 1 单位源通货的执行结果。

    执行模型与 cycle_plan 一致：从 1 单位源通货出发，每步按原始市场比例兑换，
    买边金币费 = receive × VE(to) 以金币实付。返回 (final, total_gold_fee)，
    任一买边 VE 缺失时 total_gold_fee 为 None。
    """
    amount = 1.0
    total_gold = 0.0
    gold_known = True
    for e in path:
        received = amount * edge_rate(e)
        if e.get("side") == "buy":
            ve = (gold_values or {}).get(e["to_unit"])
            if ve and ve > 0:
                total_gold += received * ve
            else:
                gold_known = False
        amount = received
    return amount, (total_gold if gold_known else None)


def best_gold_plans(rates, gold_values, targets=BASE_CURRENCIES):
    """每种目标默认通货的最佳金币获取方案（消耗金币兑换通货）。

    遍历汇率图中全部可用源单位（三默认中其余两个 + 所有 item:X），
    各自取 best_conversion 最优路径，再按 gold_unit_cost 换算金币口径：
    gold_per_unit = 每获得 1 单位目标通货消耗的金币（金币费未知时为 None）。
    best 为 gold_per_unit 最小者（None 排最后）。
    返回 [{"target", "best": {"source", "path", "final_amount", "gold_fee",
    "gold_per_unit"} | None, "alternatives": [...]}]，按 targets 顺序。
    """
    units = sorted({u for r in rates for u in (r["from_unit"], r["to_unit"])})
    plans = []
    for target in targets:
        options = []
        for src in units:
            if src == target:
                continue
            rate, path = best_conversion(rates, src, target, gold_values)
            if rate is None or not path:
                continue
            final, gold_fee = gold_unit_cost(path, gold_values)
            options.append({
                "source": src,
                "path": path,
                "final_amount": final,
                "gold_fee": gold_fee,
                "gold_per_unit": (gold_fee / final) if gold_fee is not None and final > 0 else None,
            })
        options.sort(key=lambda o: (o["gold_per_unit"] is None, o["gold_per_unit"] or 0))
        plans.append({
            "target": target,
            "best": options[0] if options else None,
            "alternatives": options[1:],
        })
    return plans


def verify_arbitrage_plan(rates, gold_values, plan, rel_tol=1e-9):
    """double check：沿 plan 的 path 逐边在原始汇率记录中定位同方向同侧记录，
    用原始比例独立重算终值与金币费（不复用 cycle_plan 内部计算），与方案值比对。

    返回 {"ok", "expected_final", "actual_final", "expected_gold", "actual_gold",
    "discrepancies"}；expected_* 为独立重算值，actual_* 为方案中的值；
    容差为 rel_tol 相对误差。
    """
    discrepancies = []
    path = plan.get("path") or []
    if not path:
        return {"ok": False, "expected_final": None, "actual_final": plan.get("final_amount"),
                "expected_gold": None, "actual_gold": plan.get("total_gold_fee"),
                "discrepancies": ["方案缺少兑换路径"]}
    amount = 1.0
    total_gold = 0.0
    gold_known = True
    for i, e in enumerate(path, 1):
        matches = [r for r in rates
                   if r["from_unit"] == e["from_unit"] and r["to_unit"] == e["to_unit"]
                   and r.get("side") == e.get("side")]
        if not matches:
            discrepancies.append(
                f"步骤 {i}：原始汇率中找不到 {e['from_unit']} → {e['to_unit']}（{e.get('side')}）")
            break
        entry = max(matches, key=edge_rate)
        r = edge_rate(entry)
        if not math.isclose(r, edge_rate(e), rel_tol=rel_tol):
            discrepancies.append(
                f"步骤 {i}：路径汇率 1:{edge_rate(e):.6g} 与原始记录 1:{r:.6g} 不一致")
        received = amount * r
        if entry.get("side") == "buy":
            ve = (gold_values or {}).get(entry["to_unit"])
            if ve and ve > 0:
                total_gold += received * ve
            else:
                gold_known = False
        amount = received
    expected_gold = total_gold if gold_known else None
    actual_final = plan.get("final_amount")
    actual_gold = plan.get("total_gold_fee")
    if not math.isclose(amount, actual_final, rel_tol=rel_tol):
        discrepancies.append(
            f"终值不一致：重算 {amount:.6g} ≠ 方案 {actual_final:.6g}")
    if (expected_gold is None) != (actual_gold is None):
        discrepancies.append(
            f"金币费已知性不一致：重算 {expected_gold}，方案 {actual_gold}")
    elif expected_gold is not None and not math.isclose(
            expected_gold, actual_gold, rel_tol=rel_tol):
        discrepancies.append(
            f"金币费不一致：重算 {expected_gold:.6g} ≠ 方案 {actual_gold:.6g}")
    return {"ok": not discrepancies,
            "expected_final": amount, "actual_final": actual_final,
            "expected_gold": expected_gold, "actual_gold": actual_gold,
            "discrepancies": discrepancies}


# ---------- 套利方案持仓优化（神圣口径） ----------

# 可作为套利本金的默认通货（其余起点的机会不参与持仓方案）
PRINCIPAL_UNITS = ("divine", "chaos", "exalted")

def arbitrage_opportunities(rates, gold_values):
    """枚举全部盈利环（原始汇率口径 rate>1，金币费是正常消耗）× 全部起点旋转，
    统一折算神圣口径的金币效率（金币转换通货的最优比例，标准以神圣石为准）。

    divine_value 用 best_conversion(rates, s, "divine") 原始汇率（gold_values=None），
    s=="divine" 时为 1；起点无法折算神圣时该条目跳过；total_gold_fee 为 None
    （VE 缺失）的旋转跳过；每环无金币费时 divine_per_10k_gold 为 None（排最后）。
    返回 [{start_unit, path, rate, profit_units, total_gold_fee, divine_value,
    profit_divine_per_loop, divine_per_10k_gold}]，按 divine_per_10k_gold 降序。
    """
    opportunities = []
    for c in find_profitable_cycles(rates):
        path = c["path"]
        for i in range(len(path)):
            rot = path[i:] + path[:i]
            plan = cycle_plan({"path": rot}, gold_values)
            fee = plan["total_gold_fee"]
            if fee is None:
                continue
            start = plan["start_unit"]
            if start == "divine":
                divine_value = 1.0
            else:
                divine_value, _ = best_conversion(rates, start, "divine")
                if divine_value is None:
                    continue
            profit_divine = plan["profit_units"] * divine_value
            per_10k = (profit_divine / fee * 10000) if fee > 0 else None
            opportunities.append({
                "start_unit": start,
                "path": rot,
                "rate": plan["rate"],
                "profit_units": plan["profit_units"],
                "total_gold_fee": fee,
                "divine_value": divine_value,
                "profit_divine_per_loop": profit_divine,
                "divine_per_10k_gold": per_10k,
            })
    opportunities.sort(key=lambda o: (o["divine_per_10k_gold"] is None,
                                      -(o["divine_per_10k_gold"] or 0)))
    return opportunities


def best_arbitrage_plan(rates, gold_values, holdings):
    """持仓口径最优套利方案：消耗金币沿价差兑换环互换来赚取本金通货。

    执行模型：每环投入 batch 个起点通货，按原始市场比例兑换一圈收回
    batch×rate 个，消耗金币 fee = fee_per_unit × batch，净得
    profit_units × batch；同一本金可重复循环，金币预算决定总环数。
    总净得 = profit_units × gold / fee_per_unit（与每环规模无关），因此
    按金币效率（每金币净得折神圣）选环即总收益最大——金币通货转换率最高。

    batch = min(起点持仓, gold / fee_per_unit)：预算跑不满整仓一环时缩减
    每环本金规模，保证 total_gold_fee = fee_per_unit × batch × loops ≤ gold
    （消耗金币永不超预算，方案可执行）。final_amount = 起点持仓 + 总净得。

    起点限 PRINCIPAL_UNITS 且对应持仓 > 0、金币预算 > 0、fee_per_unit > 0；
    无满足条件的机会时返回 None。
    check 用未缩放（1 本金口径）值调 verify_arbitrage_plan 独立复核。
    """
    gold = holdings.get("gold") or 0
    if gold <= 0:
        return None
    best = None
    best_profit_divine = None
    for opp in arbitrage_opportunities(rates, gold_values):
        start = opp["start_unit"]
        if start not in PRINCIPAL_UNITS:
            continue
        principal = holdings.get(start) or 0
        if principal <= 0:
            continue
        fee_per_unit = opp["total_gold_fee"]
        if fee_per_unit is None or fee_per_unit <= 0:
            continue
        batch = min(principal, gold / fee_per_unit)
        loops = gold / (fee_per_unit * batch)
        profit_total = opp["profit_units"] * batch * loops
        total_gold = fee_per_unit * batch * loops
        final_amount = principal + profit_total
        final_divine = final_amount * opp["divine_value"]
        profit_divine_total = profit_total * opp["divine_value"]
        if best_profit_divine is None or profit_divine_total > best_profit_divine:
            best_profit_divine = profit_divine_total
            best = (opp, principal, batch, loops, profit_total, total_gold,
                    final_amount, final_divine)
    if best is None:
        return None
    (opp, principal, batch, loops, profit_total, total_gold,
     final_amount, final_divine) = best
    plan = cycle_plan({"path": opp["path"]}, gold_values)
    steps = [{
        **s,
        "pay": s["pay"] * batch,
        "receive": s["receive"] * batch,
        "gold_fee": (s["gold_fee"] * batch if s["gold_fee"] is not None else None),
    } for s in plan["steps"]]
    check = verify_arbitrage_plan(rates, gold_values, {
        "path": opp["path"],
        "final_amount": plan["final_amount"],
        "total_gold_fee": plan["total_gold_fee"],
    })
    return {"start_unit": opp["start_unit"], "principal": principal,
            "batch": batch, "loops": loops, "gold_budget": gold,
            "profit_units": opp["profit_units"], "profit_total": profit_total,
            "final_amount": final_amount, "final_divine": final_divine,
            "steps": steps, "path": opp["path"], "rate": opp["rate"],
            "total_gold_fee": total_gold,
            "divine_value": opp["divine_value"],
            "divine_per_10k_gold": opp["divine_per_10k_gold"],
            "check": check}
