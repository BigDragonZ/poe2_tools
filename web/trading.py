"""交易页纯逻辑：汇率图、最优兑换路径、套利环检测、金币折算。

汇率以「边」表示：from_unit --(amount_from -> amount_to)--> to_unit。
基础通货 unit 固定为 exalted / chaos / divine，物品 unit 为 "item:名称"。
汇率数据由桌面端游玩工具的市场比例抓取同步入库（trade_rates.category 区分
默认/指定/自动页面），本模块只负责计算。

市场规则（用户确认的 POE2 金币交易模型）：
- 每条边分买（buy）/ 卖（sell）两侧；卖出不收金币。
- 买入的金币费 = 买入数量 × 买入通货的 Currency Exchange 值（VE，金币/个）。
- 因此 1 个通货 X ≡ VE(X) 金币，买边的有效汇率需把金币费折算成支付方通货。
"""

BASE_CURRENCIES = ["exalted", "chaos", "divine"]

BASE_LABELS = {"exalted": "崇高石", "chaos": "混沌石", "divine": "神圣石"}

ITEM_PREFIX = "item:"


def item_unit(name):
    return ITEM_PREFIX + name


def is_item_unit(unit):
    return unit.startswith(ITEM_PREFIX)


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
    """枚举兑换率乘积 > 1 的简单环（套利机会）。

    返回 [{"rate", "path"}] 按收益率降序；同一环的旋转视为同一个环。
    """
    graph = build_graph(rates)
    found = {}

    def dfs(start, node, acc, path, visited):
        for e in graph.get(node, []):
            nxt = e["to_unit"]
            if nxt == start and path:
                cycle_path = path + [e]
                rate = acc * effective_rate(e, gold_values)
                if rate > 1.0 + min_profit:
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
