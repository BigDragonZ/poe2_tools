"""交易页纯逻辑：汇率图、套利环检测、每轮口径最优套利方案与独立复核、套利候选筛选。

汇率以「边」表示：from_unit --(amount_from -> amount_to)--> to_unit。
基础通货 unit 固定为 exalted / chaos / divine，物品 unit 为 "item:名称"。
汇率数据由桌面端游玩工具的市场比例抓取同步入库（trade_rates.category 区分
默认/指定/自动页面），本模块只负责计算。

市场规则（用户确认的 POE2 金币交易模型）：
- 每条边分买（buy）/ 卖（sell）两侧；卖出不收金币。
- 买入的金币费 = 买入数量 × 买入通货的 Currency Exchange 值（VE，金币/个）。
- 因此 1 个通货 X ≡ VE(X) 金币，买边的有效汇率需把金币费折算成支付方通货。

套利核心口径（2026-10-04 确认）：套利的核心是金币换通货，不关注当前持仓；
重点只有两个——通货互换的价差（环终值 - 1），以及价差与每轮金币费的比率
（每 1 万金币净得多少神圣当量，即通货/万金币转换率）。
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


# ---------- 自动套利：候选筛选 ----------

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




# ---------- 每轮口径最优套利方案 ----------

def rates_for_arbitrage(latest, default_latest, category):
    """套利计算的汇率图：指定/自动类别并入默认类别的三通货基础比例。

    物品×单通货的往返必然亏损（市场买卖价差），盈利环需经默认通货间的边
    闭环（如 物品→混沌→神圣→物品），而默认通货间的比例只在 default 类别。
    default 类别直接用自身比例。
    """
    if category == "default":
        return list(latest)
    return list(latest) + list(default_latest)


def best_arbitrage_round(rates, gold_values):
    """每轮口径最优套利方案：金币效率最高的兑换环，以 1 单位起点通货为一轮展开。

    选环标准 = arbitrage_opportunities 首位（每 1 万金币净得折神圣最高，即
    通货/万金币转换率最高）；步骤不按持仓缩放（套利核心是金币换通货，
    每轮规模由市场挂单深度决定，与持仓无关）。返回 cycle_plan 结果附加
    path / divine_value / profit_divine_per_loop / divine_per_10k_gold /
    check（verify_arbitrage_plan 独立复核）；无盈利环或全部环金币费未知
    时返回 None。
    """
    opps = arbitrage_opportunities(rates, gold_values)
    if not opps:
        return None
    opp = opps[0]
    plan = cycle_plan({"path": opp["path"]}, gold_values)
    plan["path"] = opp["path"]
    plan["divine_value"] = opp["divine_value"]
    plan["profit_divine_per_loop"] = opp["profit_divine_per_loop"]
    plan["divine_per_10k_gold"] = opp["divine_per_10k_gold"]
    plan["check"] = verify_arbitrage_plan(rates, gold_values, plan)
    return plan

