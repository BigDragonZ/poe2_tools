#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
背包整理：F3/F4 两点标定格距 + 一键存仓。

- 标定：F3 记录第 1 格中心，F4 记录右侧相邻格中心，水平间距写入配置
- 一键存仓：Ctrl 按住，以触发时鼠标位置为第 1 格中心行优先遍历点击
- 运行中再按一次热键停止；失焦或 F12 自动中断并释放 Ctrl
"""

from __future__ import annotations

from collections.abc import Callable

from poe2_tools.config.settings import Point, Settings, save_settings
from poe2_tools.core import window
from poe2_tools.modules import batch_ops
from poe2_tools.modules.base import Logger, ToggleRunner


class BagOrganizer(ToggleRunner):
    """背包一键存仓。"""

    name = "背包整理"

    def __init__(
        self,
        settings: Settings,
        logger: Logger | None = None,
        on_calibrated: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(settings, logger)
        self._on_calibrated = on_calibrated
        self._first_point: Point | None = None

    # --------------------------------------------------------
    # 标定（F3/F4）
    # --------------------------------------------------------
    def calibrate_first(self) -> None:
        """F3：记录当前鼠标位置为第 1 格中心。"""
        if not window.is_poe_active():
            return
        pos = window.cursor_client_pos()
        if pos is None:
            return
        self._first_point = pos
        self.log(f"已记录第 1 格中心 ({pos.x}, {pos.y})，再按 F4 标定右侧相邻格")

    def calibrate_second(self) -> None:
        """F4：记录右侧相邻格中心，保存格子间距。"""
        if not window.is_poe_active():
            return
        if self._first_point is None:
            self.log("请先按 F3 标定第 1 格")
            return
        pos = window.cursor_client_pos()
        if pos is None:
            return
        p1 = self._first_point
        if pos.x <= p1.x or abs(pos.y - p1.y) > 10:
            self.log("标定失败：第 2 格必须在第 1 格右侧同一行", "WARN")
            return
        self.settings.general.sort.cell_size = pos.x - p1.x
        save_settings(self.settings)
        self.log(f"标定成功，格子间距: {self.settings.general.sort.cell_size} px")
        if self._on_calibrated is not None:
            self._on_calibrated()

    # --------------------------------------------------------
    # 一键存仓
    # --------------------------------------------------------
    def preflight(self) -> Point | None:
        if not window.is_poe_active():
            return None
        if self.settings.general.sort.cell_size <= 0:
            self.log("请先标定：F3 指向第 1 格中心，F4 指向右侧相邻格中心", "WARN")
            return None
        origin = window.cursor_client_pos()
        if origin is None:
            self.log("未找到 POE2 窗口", "ERROR")
            return None
        self.log("背包整理中，再按一次整理热键停止")
        return origin

    def _work(self, origin: Point) -> None:
        sort = self.settings.general.sort
        aborted = batch_ops.run_dump(
            origin,
            sort.cell_size,
            sort.rows,
            sort.cols,
            sort.interval_ms,
            self._should_stop,
            window.is_poe_active,
            batch_ops.BatchDriver(),
        )
        self.log("背包整理已中断" if aborted else "背包整理完成")

    def run_once(self, origin: Point) -> bool:
        """供石碑/地图完成后调用一次整理；返回是否被中断。"""
        sort = self.settings.general.sort
        return batch_ops.run_dump(
            origin,
            sort.cell_size,
            sort.rows,
            sort.cols,
            sort.interval_ms,
            self._should_stop,
            window.is_poe_active,
            batch_ops.BatchDriver(),
        )
