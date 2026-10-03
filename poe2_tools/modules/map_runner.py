#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
地图速点：批量给地图上点金/崇高/瓦尔。

流程（等价 AHK MapWorker）：
点金石×每格 1 次 → 崇高×每格 4 次 → 瓦尔×每格 1 次 →
完成后自动触发一次背包整理。
每阶段：Shift 按住 → 货币坐标右键选中 → 移动至背包逐格左键 N 次。
瓦尔腐化有动画，瓦尔阶段间隔不低于 500ms 兜底，避免漏点。
中断时不触发整理；失焦或 F12 自动中断并释放 Shift。
"""

from __future__ import annotations

from poe2_tools.config.settings import (
    CURRENCY_NAMES,
    MAP_MIN_INTERVAL_MS,
    MAP_PHASES,
    Point,
    Settings,
    currency_coord,
)
from poe2_tools.core import window
from poe2_tools.modules import batch_ops
from poe2_tools.modules.base import Logger, ToggleRunner
from poe2_tools.modules.bag import BagOrganizer


class MapRunner(ToggleRunner):
    """地图速点。"""

    name = "地图速点"

    def __init__(
        self, settings: Settings, bag: BagOrganizer, logger: Logger | None = None
    ) -> None:
        super().__init__(settings, logger)
        self._bag = bag

    def missing_currencies(self) -> list[str]:
        """返回尚未标定坐标的流程货币（中文名），供启动前检查与界面提示。"""
        return [
            CURRENCY_NAMES[key]
            for key, _ in MAP_PHASES
            if currency_coord(self.settings, key) is None
        ]

    def preflight(self) -> Point | None:
        if not window.is_poe_active():
            return None
        missing = self.missing_currencies()
        if missing:
            self.log(f"请先在「坐标」页标定「{missing[0]}」", "WARN")
            return None
        origin = self._check_common()
        if origin is not None:
            self.log("地图速点中（点金→崇高→瓦尔→整理），再按一次停止")
        return origin

    def _work(self, origin: Point) -> None:
        sort = self.settings.general.sort
        driver = batch_ops.BatchDriver()
        aborted = False
        for key, clicks in MAP_PHASES:
            coord = currency_coord(self.settings, key)
            assert coord is not None  # preflight 已校验
            interval = max(self.settings.general.map_click.interval_ms, MAP_MIN_INTERVAL_MS.get(key, 0))
            if batch_ops.apply_currency_to_bag(
                coord,
                clicks,
                origin,
                sort.cell_size,
                sort.rows,
                sort.cols,
                interval,
                self._should_stop,
                window.is_poe_active,
                driver,
            ):
                aborted = True
                break
        dumped = False
        if not aborted:
            self._bag.run_once(origin)
            dumped = True
        self.log("地图速点已中断" if aborted else f"地图速点完成{'，背包整理已触发' if dumped else ''}")
