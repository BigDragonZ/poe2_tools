#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
默认/指定通货批量抓取与交易菜单同步（业务编排层）。

- DEFAULT_CURRENCIES：三种默认通货（web 单位 / 中文名 / 游戏内英文全名），
  顺序与 web 端 BASE_CURRENCIES 一致
- default_pairs() / custom_pairs(name)：生成待抓取通货对，每对经
  CurrencyTradeScanner.scan 一次覆盖双向比例
- rates_from_scan()：把 scan 数据契约换算成交易页汇率记录——
  市场比率「x:y」= x 个「我需要的」= y 个「我拥有的」，统一换算为
  side=buy 的买边（付 HAVE 通货 + 金币费换取 WANT 通货），金币费由
  交易页面按 Currency Exchange 值（web 端维护）折算
- publish_rates()：写入 web/data/economy.db 并按 category 归入交易菜单
  对应页面（default=默认 / custom=指定 / auto=自动），同类别同方向
  （from/to/side）的旧自动记录整体替换，每次只保留最近一次
- ExchangeScanRunner：顺序执行多对抓取（同步阻塞，界面层在工作线程
  调用），单对失败不中断其余，全部完成后一次性发布；最佳兑换路径与
  金币折算不在此计算，由交易页面（/api/trade/state）按最新汇率现算
"""

from __future__ import annotations

from collections.abc import Callable

from poe2_tools.modules.market.scanner import CurrencyTradeScanner

# (web 单位, 中文名, 游戏内英文全名)；顺序对齐交易·默认页顶部
DEFAULT_CURRENCIES: tuple[tuple[str, str, str], ...] = (
    ("exalted", "崇高石", "Exalted Orb"),
    ("chaos", "混沌石", "Chaos Orb"),
    ("divine", "神圣石", "Divine Orb"),
)

# 抓取类别 → 交易菜单三级页面标签（与 web/db.py TRADE_CATEGORIES 一致）
CATEGORY_LABELS: dict[str, str] = {"default": "默认", "custom": "指定", "auto": "自动"}

# 指定通货在交易页中的单位前缀（与 web/trading.py ITEM_PREFIX 一致）
ITEM_PREFIX = "item:"

# 通货对：(A 单位, A 游戏名, B 单位, B 游戏名)
CurrencyPair = tuple[str, str, str, str]


def default_pairs() -> list[CurrencyPair]:
    """三种默认通货的两两组合（3 对，每对 scan 覆盖双向）。"""
    pairs: list[CurrencyPair] = []
    for i in range(len(DEFAULT_CURRENCIES)):
        for j in range(i + 1, len(DEFAULT_CURRENCIES)):
            a_unit, _, a_name = DEFAULT_CURRENCIES[i]
            b_unit, _, b_name = DEFAULT_CURRENCIES[j]
            pairs.append((a_unit, a_name, b_unit, b_name))
    return pairs


def custom_pairs(currency_name: str) -> list[CurrencyPair]:
    """指定通货与三种默认通货的组合（3 对）；指定通货单位为 item:名称。"""
    custom_unit = ITEM_PREFIX + currency_name
    return [
        (custom_unit, currency_name, unit, game_name)
        for unit, _, game_name in DEFAULT_CURRENCIES
    ]


def parse_ratio(ratio: str) -> tuple[float, float] | None:
    """把「x:y」比例文本解析为两个数（去千分位逗号）；无法解析返回 None。"""
    parts = ratio.split(":")
    if len(parts) != 2:
        return None
    try:
        x = float(parts[0].replace(",", ""))
        y = float(parts[1].replace(",", ""))
    except ValueError:
        return None
    if x <= 0 or y <= 0:
        return None
    return x, y


def rates_from_scan(result: dict, unit_a: str, unit_b: str) -> list[dict]:
    """把 scan(A, B) 的数据契约换算为交易页汇率记录（每方向取第 1 条挂单）。

    b_to_a（想要 A、付出 B）比例 x:y → x A = y B → 买边 from=B to=A；
    a_to_b（想要 B、付出 A）比例 x:y → x B = y A → 买边 from=A to=B。
    某方向无挂单或比例无法解析时跳过该方向。
    """
    rates: list[dict] = []
    for key, from_unit, to_unit in (("b_to_a", unit_b, unit_a), ("a_to_b", unit_a, unit_b)):
        listings = result.get(key) or []
        if not listings:
            continue
        parsed = parse_ratio(str(listings[0].get("ratio", "")))
        if parsed is None:
            continue
        want, have = parsed
        rates.append({
            "from_unit": from_unit,
            "to_unit": to_unit,
            "amount_from": have,
            "amount_to": want,
            "side": "buy",
        })
    return rates


def publish_rates(rates: list[dict], category: str = "default") -> int:
    """写入交易菜单数据库（web/data/economy.db），返回写入条数。

    category 决定归入交易菜单哪个三级页面（default 默认 / custom 指定 /
    auto 自动）。延迟导入 web.db：桌面端与 Web 应用为独立进程，仅在此刻
    产生耦合。
    """
    from web import db

    db.init_db()
    return db.replace_auto_trade_rates(rates, category=category)


class ExchangeScanRunner:
    """多对通货顺序抓取 + 汇总发布（同步阻塞，界面层在工作线程调用）。"""

    def __init__(
        self,
        scanner: CurrencyTradeScanner,
        logger: Callable[[str, str], None] | None = None,
        publisher: Callable[[list[dict], str], int] = publish_rates,
    ) -> None:
        self._scanner = scanner
        self._logger = logger
        self._publisher = publisher

    def _log(self, message: str, level: str = "INFO") -> None:
        if self._logger is not None:
            self._logger(message, level)

    def run(
        self,
        pairs: list[CurrencyPair],
        category: str = "default",
        progress: Callable[[str], None] | None = None,
    ) -> dict:
        """逐对抓取并按 category 发布到交易菜单对应页面。

        返回 {"pairs", "rates", "published", "category", "errors"}。
        坐标未标定时 preflight 直接抛 UnsetCoordinateError（不产生任何点击）；
        单对抓取异常记入 errors 并继续下一对。
        """
        self._scanner.preflight()
        rates: list[dict] = []
        errors: list[str] = []
        for a_unit, a_name, b_unit, b_name in pairs:
            label = f"{a_name} ↔ {b_name}"
            if progress is not None:
                progress(f"抓取中：{label}")
            self._log(f"批量抓取：{label}")
            try:
                result = self._scanner.scan(a_name, b_name)
            except Exception as exc:
                errors.append(f"{label}：{exc}")
                self._log(f"批量抓取失败（{label}）：{exc}", "WARN")
                continue
            rates.extend(rates_from_scan(result, a_unit, b_unit))
        published = self._publisher(rates, category) if rates else 0
        if published:
            page_label = CATEGORY_LABELS.get(category, category)
            self._log(f"已同步 {published} 条比例到交易·{page_label}页")
        return {
            "pairs": len(pairs),
            "rates": len(rates),
            "published": published,
            "category": category,
            "errors": errors,
        }
