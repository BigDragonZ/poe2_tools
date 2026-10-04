#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""交易·自动套利抓取编排（业务层）。

流程：load_candidates() 从 Web 经济数据（通货模块快照）筛选价值区间内的候选
通货 → auto_pairs() 生成 候选 × 三默认通货 的抓取对 → 复用
ExchangeScanRunner（category="auto"）批量抓取并同步 Web「交易 → 自动」页；
最佳金币获取方案与套利方案由交易页面（/api/trade/state）按最新汇率现算。

桌面端与 Web 应用为独立进程，web.* 一律延迟导入（与 publish_rates 先例一致）。
"""

from __future__ import annotations

from collections.abc import Callable

from poe2_tools.modules.market.exchange import (
    CATEGORY_LABELS,
    ExchangeScanRunner,
    auto_pairs,
    publish_rates,
)
from poe2_tools.modules.market.scanner import CurrencyTradeScanner

# 候选通货默认价值区间（神圣计，与 web/trading.py DEFAULT_CANDIDATE_LO/HI 一致）
DEFAULT_RANGE_LO = 0.5
DEFAULT_RANGE_HI = 20.0


class ArbitrageDataError(Exception):
    """候选数据缺失（经济快照未抓取或区间内无候选）。"""


def load_candidates(lo: float = DEFAULT_RANGE_LO, hi: float = DEFAULT_RANGE_HI,
                    db_path=None) -> list[dict]:
    """从 economy.db 通货模块快照筛选候选通货（web.trading.filter_currency_candidates）。

    无快照或区间内无候选时抛 ArbitrageDataError（中文提示先在 Web 端刷新数据）。
    """
    from web import db, trading

    db.init_db(db_path)
    raw = db.get_setting("chaos_per_divine", db_path=db_path)
    chaos_per_divine = float(raw) if raw else None
    rows = db.get_currency_snapshots(db_path=db_path)
    if not rows:
        raise ArbitrageDataError(
            "没有通货经济数据：请先在 Web 端刷新「经济 → 通货」模块快照")
    candidates = trading.filter_currency_candidates(
        rows, chaos_per_divine, lo=lo, hi=hi)
    if not candidates:
        raise ArbitrageDataError(
            f"价值区间 {lo}~{hi} 神圣内没有候选通货：请调整区间或先在 Web 端刷新经济数据")
    return candidates


def candidates_missing_gold_costs(candidates: list[dict], db_path=None) -> list[str]:
    """候选中信息库缺少 Currency Exchange 值（金币消耗）的英文名列表。

    按归一化名称（canon_item_name）匹配，抹平撇号等标点差异（信息库 wiki 名
    Perfect Jeweller's Orb ↔ 游戏内搜索名 Perfect Jewellers Orb）。
    缺失通货的金币口径计算（金币获取方案/金币费）会为 None，仅作警告。
    """
    from web import db, trading

    costs = db.get_gold_costs_by_names_en(db_path=db_path)
    known = {trading.canon_item_name(n) for n in costs}
    return [c["name_en"] for c in candidates
            if trading.canon_item_name(c["name_en"]) not in known]


class ArbitrageScanRunner:
    """自动套利批量抓取：候选筛选 → auto_pairs → ExchangeScanRunner（category=auto）。"""

    def __init__(
        self,
        scanner: CurrencyTradeScanner,
        logger: Callable[[str, str], None] | None = None,
        publisher: Callable[[list[dict], str], int] = publish_rates,
    ) -> None:
        self._logger = logger
        self._runner = ExchangeScanRunner(scanner, logger=logger, publisher=publisher)

    def _log(self, message: str, level: str = "INFO") -> None:
        if self._logger is not None:
            self._logger(message, level)

    def run(
        self,
        lo: float = DEFAULT_RANGE_LO,
        hi: float = DEFAULT_RANGE_HI,
        progress: Callable[[str], None] | None = None,
    ) -> dict:
        """筛选候选并批量抓取同步交易·自动页（同步阻塞，界面层在工作线程调用）。

        返回 ExchangeScanRunner.run 的汇总并附加 {"candidates", "missing_gold_costs"}；
        候选缺 Currency Exchange 值的警告并入 "warnings"。
        """
        candidates = load_candidates(lo, hi)
        self._log(f"自动套利候选：{len(candidates)} 个通货（{lo}~{hi} 神圣）")
        pairs = auto_pairs([c["name_en"] for c in candidates])
        missing = candidates_missing_gold_costs(candidates)
        summary = self._runner.run(pairs, category="auto", progress=progress)
        warnings = list(summary["warnings"])
        if missing:
            warning = ("以下候选通货缺少 Currency Exchange 值"
                       "（金币口径计算缺失）：" + "、".join(missing))
            warnings.append(warning)
            self._log(warning, "WARN")
        summary["warnings"] = warnings
        summary["candidates"] = candidates
        summary["missing_gold_costs"] = missing
        page_label = CATEGORY_LABELS.get(summary["category"], summary["category"])
        self._log(
            f"自动套利抓取完成：{len(candidates)} 个候选、{summary['pairs']} 对，"
            f"已同步 {summary['published']} 条比例到交易·{page_label}页")
        return summary
