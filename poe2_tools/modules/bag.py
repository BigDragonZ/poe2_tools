#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
背包整理：识别仓库 → 自动开箱 → 背包网格识别 → Ctrl+左键批量存仓。

F1 流程（2026-10-14 重构，替代旧「鼠标=第 1 格」盲点流程）：
1. 亮度探针检测仓库是否已打开
2. 未打开：OCR 定位世界中「倉庫」牌匾标签（排除右上角地图面板），
   左键点标签下方箱子本体（人物自动走过去开箱），轮询等待打开，
   识别/开箱各重试 3 次，失败提示手动兜底（手动开仓库再按 F1）
3. 背包网格：当前分辨率档已有识别结果（[BagGrid]）直接用；
   否则 OpenCV 长直线晶格拟合识别（原点+格距+行列）并存档
4. Ctrl 按住逐格左键转移（跳过前 SkipCols 列白名单），不校验结果，
   完成后保持仓库打开

标定：F3/F4 格距标定保留（石碑/地图速点仍沿用「鼠标=第 1 格」旧约定）。
中断：运行中再按 F1 / 失焦 / F12 立即停止并释放 Ctrl。
"""

from __future__ import annotations

import time
from collections.abc import Callable

from poe2_tools.config.settings import Point, Settings, save_settings
from poe2_tools.core import window
from poe2_tools.core.ocr import OcrEngine, RapidOcrEngine
from poe2_tools.modules import batch_ops
from poe2_tools.modules.base import Logger, ToggleRunner
from poe2_tools.modules.stash import detect
from poe2_tools.modules.stash.grid import BagGrid, detect_bag_grid

# 开箱：点击后轮询间隔 / 单次等待超时 / 最大点击次数（人物走过去需要时间）
OPEN_POLL_MS = 500
OPEN_TIMEOUT_MS = 10_000
OPEN_MAX_ATTEMPTS = 3
# OCR 定位箱子重试次数（每次重新截屏）
LOCATE_MAX_ATTEMPTS = 3
# 仓库打开后等面板渲染稳定再做网格识别
PANEL_SETTLE_MS = 800
# 网格识别重试次数
GRID_MAX_ATTEMPTS = 3
# 「重新识别背包网格」按钮：点击时焦点在工具窗口，轮询等待切回游戏前台（毫秒）
RECOGNIZE_WAIT_POLL_MS = 500
RECOGNIZE_WAIT_TIMEOUT_MS = 15_000
# 切回前台后等画面稳定再截图
RECOGNIZE_SETTLE_MS = 1000


class BagOrganizer(ToggleRunner):
    """背包一键存仓（自动开箱 + 网格识别 + 批量转移）。"""

    name = "背包整理"

    def __init__(
        self,
        settings: Settings,
        logger: Logger | None = None,
        on_calibrated: Callable[[], None] | None = None,
        ocr: OcrEngine | None = None,
    ) -> None:
        super().__init__(settings, logger)
        self._on_calibrated = on_calibrated
        self._ocr = ocr
        self._first_point: Point | None = None

    # --------------------------------------------------------
    # 标定（F3/F4，供石碑/地图速点的旧约定使用）
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
    # F1 主流程
    # --------------------------------------------------------
    def preflight(self) -> Point | None:
        if not window.is_poe_active():
            return None
        self.log("背包整理中，再按一次整理热键停止")
        return Point(0, 0)  # 新流程不依赖鼠标位置（网格由识别/配置提供）

    def _work(self, origin: Point) -> None:
        del origin  # 不使用
        driver = batch_ops.BatchDriver()
        if not detect.stash_open() and not self._open_stash(driver):
            return
        grid = self._ensure_bag_grid()
        if grid is None:
            return
        sort = self.settings.general.sort
        aborted = batch_ops.run_dump(
            grid.origin, grid.cell, grid.rows, grid.cols,
            sort.interval_ms, self._should_stop, window.is_poe_active,
            driver, skip_cols=sort.skip_cols,
        )
        if aborted:
            self.log("背包整理已中断")
        else:
            skip = f"（跳过前 {sort.skip_cols} 列）" if sort.skip_cols > 0 else ""
            self.log(f"背包整理完成{skip}，仓库保持打开")

    # --------------------------------------------------------
    # 阶段一：自动开箱
    # --------------------------------------------------------
    def _open_stash(self, driver: batch_ops.BatchDriver) -> bool:
        """OCR 定位仓库箱子 → 点击 → 轮询等待打开。成功返回 True。"""
        for attempt in range(1, OPEN_MAX_ATTEMPTS + 1):
            if self._should_stop() or not window.is_poe_active():
                return False
            point = self._locate_chest()
            if point is None:
                continue  # _locate_chest 内部已重试与记录
            self.log(f"已定位仓库箱子 ({point.x}, {point.y})，点击开箱（第 {attempt} 次）")
            driver.click_client(point)
            if self._wait_stash_open():
                return True
            self.log(f"点击后 {OPEN_TIMEOUT_MS // 1000} 秒内仓库未打开", "WARN")
        self.log("自动开箱失败：请手动打开仓库后再按整理热键（检测到已开会直接转移）", "WARN")
        return False

    def _locate_chest(self) -> Point | None:
        """OCR 定位仓库箱子点击点，重试 LOCATE_MAX_ATTEMPTS 次。"""
        for attempt in range(1, LOCATE_MAX_ATTEMPTS + 1):
            if self._should_stop() or not window.is_poe_active():
                return None
            if self._ocr is None:
                self._ocr = RapidOcrEngine()
            point = detect.locate_stash_chest(self._ocr)
            if point is not None:
                return point
            self.log(f"未识别到「倉庫」标签（第 {attempt}/{LOCATE_MAX_ATTEMPTS} 次）", "WARN")
            time.sleep(0.5)
        return None

    def _wait_stash_open(self) -> bool:
        """轮询等待仓库打开（人物走过去需要时间），超时返回 False。"""
        waited = 0
        while waited < OPEN_TIMEOUT_MS:
            if self._should_stop() or not window.is_poe_active():
                return False
            if detect.stash_open():
                time.sleep(PANEL_SETTLE_MS / 1000)  # 等面板渲染稳定
                return True
            time.sleep(OPEN_POLL_MS / 1000)
            waited += OPEN_POLL_MS
        return False

    # --------------------------------------------------------
    # 阶段二：背包网格（档复用 / OpenCV 识别存档）
    # --------------------------------------------------------
    def _ensure_bag_grid(self) -> BagGrid | None:
        """取背包网格：当前分辨率档已有识别结果直接用，否则识别并存档。"""
        bg = self.settings.bag_grid
        if bg.recognized:
            return BagGrid(Point(bg.origin_x, bg.origin_y), bg.cell, bg.rows, bg.cols)
        grid = self._recognize_grid()
        if grid is None:
            self.log(
                "背包网格识别失败：请保持仓库打开后点「通用」页「重新识别背包网格」，"
                "或检查画面是否被遮挡",
                "WARN",
            )
            return None
        bg.origin_x, bg.origin_y = grid.origin.x, grid.origin.y
        bg.cell, bg.rows, bg.cols = grid.cell, grid.rows, grid.cols
        save_settings(self.settings)
        self.log(
            f"背包网格识别成功：第 1 格 ({grid.origin.x}, {grid.origin.y})，"
            f"格距 {grid.cell}px，{grid.rows} 行 × {grid.cols} 列"
            f"{f'（已存 {self.settings.coords_profile} 档）' if self.settings.coords_profile else ''}"
        )
        return grid

    def _recognize_grid(self) -> BagGrid | None:
        """截屏识别背包网格，重试 GRID_MAX_ATTEMPTS 次。"""
        for attempt in range(1, GRID_MAX_ATTEMPTS + 1):
            if self._should_stop() or not window.is_poe_active():
                return None
            image = detect.screenshot_client()
            if image is not None:
                grid = detect_bag_grid(image)
                if grid is not None:
                    return grid
            self.log(f"背包网格识别失败（第 {attempt}/{GRID_MAX_ATTEMPTS} 次）", "WARN")
            time.sleep(0.5)
        return None

    def recognize_grid_now(self) -> bool:
        """「重新识别背包网格」按钮入口：清掉存档强制重识别（需仓库已打开）。

        点击按钮时焦点在工具窗口：先轮询等待切回 POE2 前台
        （RECOGNIZE_WAIT_TIMEOUT_MS 内有效），切回后等画面稳定再识别。
        """
        self.log("请切回 POE2 窗口（仓库需保持打开），检测到前台后自动识别背包网格…")
        waited = 0
        while not window.is_poe_active():
            if waited >= RECOGNIZE_WAIT_TIMEOUT_MS:
                self.log("等待 POE2 前台超时，未识别", "WARN")
                return False
            time.sleep(RECOGNIZE_WAIT_POLL_MS / 1000)
            waited += RECOGNIZE_WAIT_POLL_MS
        time.sleep(RECOGNIZE_SETTLE_MS / 1000)
        if not detect.stash_open():
            self.log("请先打开仓库再识别背包网格", "WARN")
            return False
        self.settings.bag_grid.cell = 0  # 清档强制重识别
        grid = self._ensure_bag_grid()
        return grid is not None

    # --------------------------------------------------------
    # 供石碑/地图完成后调用一次整理（沿用旧约定：鼠标位置 = 第 1 格）
    # --------------------------------------------------------
    def run_once(self, origin: Point) -> bool:
        """旧约定的一键存仓（石碑/地图模块内部调用）；返回是否被中断。"""
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
