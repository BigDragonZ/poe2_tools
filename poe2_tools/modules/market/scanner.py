#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
通货市场交换比例抓取（业务逻辑控制器）。

流程（游戏内置交易市场界面）：
1. Phase 1（B 换 A）：WANT 选通货 A → HAVE 选通货 B → 点市场比率 →
   截屏结果面板 → OCR 解析得到 result_b_to_a
2. Phase 2（A 换 B）：Ctrl+左键点「我需要的」反转选中 → 点市场比率 →
   截屏 → OCR 解析得到 result_a_to_b

坐标复用开发页测量槽位（[Measure]）：point1~5 = 我需要的/我拥有的/
搜索框/市场比率按键/搜索结果首项，range3 = 结果面板；未标定抛
UnsetCoordinateError。driver/ocr 可注入替身，便于纯逻辑单测。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from poe2_tools.config.settings import Point, Settings
from poe2_tools.modules.market.driver import UIActionDriver, copy_to_clipboard
from poe2_tools.modules.market.ocr import OcrEngine, RapidOcrEngine
from poe2_tools.modules.market.parser import parse_market_blocks

if TYPE_CHECKING:
    from PIL import Image

# 抓取调试截图目录（按 阶段+通货对 命名，同对重复抓取覆盖，便于人工核对每对截屏区域）
DEBUG_DIR = Path(__file__).resolve().parent.parent.parent.parent / "logs" / "market"

# 「我需要的」/「我拥有的」选择模式
MODE_WANT = "WANT"
MODE_HAVE = "HAVE"

# 测量槽位 → 市场界面元素（见模块 docstring）
POINT_SLOTS = {
    "我需要的": 1,
    "我拥有的": 2,
    "搜索框": 3,
    "市场比率按键": 4,
    "搜索结果首项": 5,
}
RESULT_RANGE_SLOT = 3


def _debug_name(phase: str, currency_a: str, currency_b: str) -> str:
    """调试图文件名：阶段 + 通货对（非法字符转下划线，同对重复抓取覆盖）。"""
    slug = lambda s: re.sub(r"[^0-9A-Za-z一-鿿]+", "_", s).strip("_")
    return f"{phase}_{slug(currency_a)}__{slug(currency_b)}"


class UnsetCoordinateError(Exception):
    """坐标/范围未标定（中文原因，直接展示给用户）。"""


class CurrencyTradeScanner:
    """
    通货市场比例抓取控制器。

    settings 提供测量坐标与延时；driver 默认 UIActionDriver（真实键鼠），
    ocr 默认 RapidOcrEngine，测试时注入假实现。scan 为同步阻塞调用，
    界面层需在工作线程中执行。
    """

    def __init__(
        self,
        settings: Settings,
        driver: UIActionDriver | None = None,
        ocr: OcrEngine | None = None,
        logger: Callable[[str, str], None] | None = None,
    ) -> None:
        self.settings = settings
        self._logger = logger
        scan_cfg = settings.market_scan
        self._driver = driver or UIActionDriver(scan_cfg.click_delay_ms)
        self._ocr = ocr or RapidOcrEngine()
        self._search_load_delay_ms = scan_cfg.search_load_delay_ms
        self._ui_refresh_delay_ms = scan_cfg.ui_refresh_delay_ms
        self._select_delay_ms = scan_cfg.select_delay_ms

    def log(self, message: str, level: str = "INFO") -> None:
        print(message)
        if self._logger is not None:
            self._logger(message, level)

    # --------------------------------------------------------
    # 标定校验
    # --------------------------------------------------------
    def _required_points(self) -> dict[str, Point]:
        """取齐 5 个市场坐标点；缺任一槽位抛 UnsetCoordinateError。"""
        points = self.settings.dev.measure_points
        missing = [name for name, slot in POINT_SLOTS.items() if slot not in points]
        if missing:
            raise UnsetCoordinateError(
                "市场坐标未标定：" + "、".join(missing) + "（请在开发页测量后重试）"
            )
        return {name: points[slot] for name, slot in POINT_SLOTS.items()}

    def _result_range(self) -> tuple[int, int, int, int]:
        """取结果面板框选范围（含配置偏移修正）；未标定抛 UnsetCoordinateError。"""
        rect = self.settings.dev.measure_ranges.get(RESULT_RANGE_SLOT)
        if rect is None:
            raise UnsetCoordinateError(
                f"结果面板范围未标定（开发页框选 range{RESULT_RANGE_SLOT}）"
            )
        ox = self.settings.market_scan.range_offset_x
        oy = self.settings.market_scan.range_offset_y
        return (rect[0] + ox, rect[1] + oy, rect[2] + ox, rect[3] + oy)

    def preflight(self) -> None:
        """执行前校验坐标与范围完整，不满足时抛 UnsetCoordinateError。"""
        self._required_points()
        self._result_range()

    # --------------------------------------------------------
    # 搜索子流程
    # --------------------------------------------------------
    def search_and_select(self, mode: str, currency_name: str) -> None:
        """
        选中通货：剪贴板写入名称 → 点 WANT/HAVE 入口 → 点搜索框粘贴 →
        等待搜索下拉刷新 → 点搜索结果首项 → 等待选中生效。
        """
        if mode not in (MODE_WANT, MODE_HAVE):
            raise ValueError(f"未知选择模式：{mode}")
        points = self._required_points()
        entry = points["我需要的"] if mode == MODE_WANT else points["我拥有的"]
        copy_to_clipboard(currency_name)
        self._driver.click_position(entry)
        self._driver.input_from_clipboard(points["搜索框"])
        self._driver.sleep_ms(self._search_load_delay_ms)
        self._driver.click_position(points["搜索结果首项"])
        self._driver.sleep_ms(self._select_delay_ms)

    # --------------------------------------------------------
    # OCR 解析
    # --------------------------------------------------------
    def parse_market_image(self, image: "Image.Image") -> list[dict]:
        """对结果面板截图 OCR（带坐标文本块）并解析为挂单列表；无比例时返回空数组。"""
        blocks = self._ocr.recognize_blocks(image)
        self.log(f"OCR 识别 {len(blocks)} 块：{' | '.join(b.text for b in blocks)}", "DEBUG")
        return parse_market_blocks(blocks)

    def _save_debug_image(self, image: "Image.Image", name: str) -> None:
        """把结果面板截图存到 logs/market/ 供人工核对（失败仅告警，不中断抓取）。"""
        if not hasattr(image, "save"):
            return  # 测试注入的假图像直接跳过
        try:
            DEBUG_DIR.mkdir(parents=True, exist_ok=True)
            path = DEBUG_DIR / f"{name}.png"
            image.save(path)
            self.log(f"调试截图已保存：{path}", "DEBUG")
        except Exception as exc:
            self.log(f"调试截图保存失败：{exc}", "WARN")

    def _capture_and_parse(self, rect: tuple[int, int, int, int], name: str) -> list[dict]:
        """截屏 + 保存调试图 + OCR 解析；任一环节失败记告警并返回空数组（不拖垮另一方向）。"""
        try:
            image = self._driver.capture_region(rect)
        except Exception as exc:
            self.log(f"截屏失败（{name}）：{exc}", "WARN")
            return []
        self._save_debug_image(image, name)
        try:
            return self.parse_market_image(image)
        except Exception as exc:
            self.log(f"OCR 解析失败（{name}）：{exc}", "WARN")
            return []

    def _capture_with_retry(
        self, rect: tuple[int, int, int, int], name: str, points: dict[str, Point]
    ) -> list[dict]:
        """
        截屏解析，空结果时重试一次（再点市场比率按键 → 等刷新 → 再截屏），
        规避面板首次未刷新导致的空抓取。
        """
        result = self._capture_and_parse(rect, name)
        if result:
            return result
        self.log(f"{name} 首次未解析到挂单，重试一次", "WARN")
        self._driver.click_position(points["市场比率按键"])
        self._driver.sleep_ms(self._ui_refresh_delay_ms)
        return self._capture_and_parse(rect, name)

    # --------------------------------------------------------
    # 主流程
    # --------------------------------------------------------
    def scan(self, currency_a: str, currency_b: str) -> dict:
        """
        抓取 A/B 双向兑换比例与存量，返回标准数据契约：
        {"success": True, "pair": "A <-> B", "b_to_a": [...], "a_to_b": [...]}
        某方向无可用交易时对应列表为空数组。
        """
        self.preflight()
        points = self._required_points()
        rect = self._result_range()

        # Phase 1：B 换 A（想要 A，付出 B）
        self.log(f"市场抓取：{currency_b} → {currency_a}")
        self.search_and_select(MODE_WANT, currency_a)
        self.search_and_select(MODE_HAVE, currency_b)
        self._driver.click_position(points["市场比率按键"])
        self._driver.sleep_ms(self._ui_refresh_delay_ms)
        result_b_to_a = self._capture_with_retry(
            rect, _debug_name("b_to_a", currency_a, currency_b), points)
        self.log(f"{currency_b} → {currency_a}：{len(result_b_to_a)} 条挂单")

        # Phase 2：A 换 B（Ctrl+左键点「我需要的」反转选中方向）
        self.log(f"市场抓取：{currency_a} → {currency_b}")
        self._driver.click_position(points["我需要的"], modifier="Ctrl")
        self._driver.click_position(points["市场比率按键"])
        self._driver.sleep_ms(self._ui_refresh_delay_ms)
        result_a_to_b = self._capture_with_retry(
            rect, _debug_name("a_to_b", currency_a, currency_b), points)
        self.log(f"{currency_a} → {currency_b}：{len(result_a_to_b)} 条挂单")

        return {
            "success": True,
            "pair": f"{currency_a} <-> {currency_b}",
            "b_to_a": result_b_to_a,
            "a_to_b": result_a_to_b,
        }
