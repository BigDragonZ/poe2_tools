#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
石碑速点：批量把货币应用到石碑/装备上。

流程（等价 AHK WaystoneWorker）：
Shift 按住 → 移动到所选货币坐标右键选中 → 背包逐格左键 →
完成后自动触发一次背包整理。
中断时不触发整理；失焦或 F12 自动中断并释放 Shift。
"""

from __future__ import annotations

from poe2_tools.config.settings import CURRENCY_NAMES, Point, Settings, currency_coord
from poe2_tools.core import window
from poe2_tools.modules import batch_ops
from poe2_tools.modules.base import Logger, ToggleRunner
from poe2_tools.modules.bag import BagOrganizer


class WaystoneRunner(ToggleRunner):
    """石碑速点。"""

    name = "石碑速点"

    def __init__(
        self, settings: Settings, bag: BagOrganizer, logger: Logger | None = None
    ) -> None:
        super().__init__(settings, logger)
        self._bag = bag

    def preflight(self) -> Point | None:
        if not window.is_poe_active():
            return None
        tablet = self.settings.general.tablet
        if currency_coord(self.settings, tablet.currency, tablet.tier) is None:
            name = CURRENCY_NAMES.get(tablet.currency, tablet.currency)
            self.log(f"请先在「坐标」页标定「{name}」", "WARN")
            return None
        origin = self._check_common()
        if origin is not None:
            self.log("石碑速点中，再按一次停止")
        return origin

    def _work(self, origin: Point) -> None:
        tablet = self.settings.general.tablet
        sort = self.settings.general.sort
        coord = currency_coord(self.settings, tablet.currency, tablet.tier)
        assert coord is not None  # preflight 已校验
        driver = batch_ops.BatchDriver()
        aborted = batch_ops.apply_currency_to_bag(
            coord,
            1,
            origin,
            sort.cell_size,
            sort.rows,
            sort.cols,
            tablet.interval_ms,
            self._should_stop,
            window.is_poe_active,
            driver,
        )
        dumped = False
        if not aborted:
            self._bag.run_once(origin)
            dumped = True
        self.log("石碑速点已中断" if aborted else f"石碑速点完成{'，背包整理已触发' if dumped else ''}")
