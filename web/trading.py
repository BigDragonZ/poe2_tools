"""交易助手纯逻辑：汇率图、最优兑换路径、套利环检测。

汇率以「边」表示：from_unit --(amount_from -> amount_to)--> to_unit。
基础通货 unit 固定为 exalted / chaos / divine，物品 unit 为 "item:名称"。
所有汇率由用户在游戏内观测后手动录入，本模块只负责计算。
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


def build_graph(rates):
    """from_unit -> [汇率记录...]。"""
    graph = {}
    for r in rates:
        graph.setdefault(r["from_unit"], []).append(r)
    return graph


def best_conversion(rates, src, dst):
    """在汇率图中找 src -> dst 兑换率最高的简单路径（不重复节点，避免套利环无限放大）。

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
            dfs(nxt, acc * edge_rate(e), path, visited)
            path.pop()
            visited.discard(nxt)

    dfs(src, 1.0, [], {src})
    if best_path is None:
        return None, None
    return best_rate, best_path


def find_profitable_cycles(rates, min_profit=1e-9):
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
                rate = acc * edge_rate(e)
                if rate > 1.0 + min_profit:
                    units = [p["from_unit"] for p in cycle_path]
                    key = min(tuple(units[i:] + units[:i]) for i in range(len(units)))
                    if key not in found or found[key]["rate"] < rate:
                        found[key] = {"rate": rate, "path": cycle_path}
            elif nxt not in visited:
                visited.add(nxt)
                dfs(start, nxt, acc * edge_rate(e), path + [e], visited)
                visited.discard(nxt)

    for start in list(graph.keys()):
        dfs(start, start, 1.0, [], {start})
    return sorted(found.values(), key=lambda c: c["rate"], reverse=True)
