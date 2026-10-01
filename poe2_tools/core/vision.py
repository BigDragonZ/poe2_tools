#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
视觉检测：窗口截图 + OpenCV 模板匹配（FindText 的 Python 替代）。

- 截图用 mss（按屏幕坐标抓取小区域，毫秒级开销）
- 模板匹配用 cv2.matchTemplate，阈值 0.9 ≈ FindText 容错 10%
- 无模板时用白色像素检测兜底（数字为纯白，容差 ±20）
- CycloneWatcher 在独立线程中按周期检测、边沿触发回调，
  不阻塞主线程与 UI；全黑帧（截图失败）保持上次状态不误判
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from pathlib import Path

import cv2
import mss
import numpy as np

from poe2_tools.config.settings import (
    CYC_DETECT_KEYS,
    CYC_DETECT_MS,
    CYC_MATCH_THRESHOLD,
    CYC_NUM_HH,
    CYC_NUM_HW,
    CYC_TEMPLATE_RADIUS,
    Point,
)
from poe2_tools.core import window

# 白色像素容差（±20）
WHITE_TOLERANCE = 20


# ============================================================
# 截图与匹配（纯逻辑，可单测）
# ============================================================
def capture_region(x: int, y: int, width: int, height: int) -> np.ndarray:
    """抓取屏幕区域，返回 BGR 图像。"""
    with mss.mss() as sct:
        shot = sct.grab({"left": x, "top": y, "width": width, "height": height})
        return np.array(shot)[:, :, :3]  # BGRA -> BGR


def match_template(region: np.ndarray, template: np.ndarray,
                   threshold: float = CYC_MATCH_THRESHOLD) -> bool:
    """模板匹配：region 中存在与 template 相似度 ≥ threshold 的位置时返回 True。"""
    if region.size == 0 or template.size == 0:
        return False
    if region.shape[0] < template.shape[0] or region.shape[1] < template.shape[1]:
        return False
    # 常量模板（纯黑/纯白）归一化相关系数无意义，OpenCV 会给出误导性结果
    if float(template.std()) < 1e-6:
        return False
    result = cv2.matchTemplate(region, template, cv2.TM_CCOEFF_NORMED)
    return bool(result.max() >= threshold)


def has_bright_pixel(region: np.ndarray, tolerance: int = WHITE_TOLERANCE) -> bool:
    """白色像素兜底：区域中存在接近纯白（各通道 ≥ 255 - tolerance）的像素。"""
    if region.size == 0:
        return False
    return bool(np.all(region >= 255 - tolerance, axis=2).any())


def load_template(path: Path) -> np.ndarray | None:
    """加载模板图片；不存在或损坏返回 None。"""
    if not path.exists():
        return None
    img = cv2.imread(str(path))
    return img if img is not None and img.size > 0 else None


def grab_template_image(center: Point, radius: int = CYC_TEMPLATE_RADIUS) -> np.ndarray | None:
    """以客户区坐标为中心截取模板图像（供 UI「截图」按钮使用）。"""
    origin = window.client_origin()
    if origin is None:
        return None
    x = origin.x + center.x - radius
    y = origin.y + center.y - radius
    return capture_region(x, y, radius * 2, radius * 2)


# ============================================================
# 边沿触发（纯逻辑，可单测）
# ============================================================
class EdgeTrigger:
    """边沿触发器：信号从「无」变「有」时只触发一次。"""

    def __init__(self) -> None:
        self._state = False

    def update(self, found: bool) -> bool:
        """更新检测状态；返回本次是否应触发（上升沿）。"""
        pressed = found and not self._state
        self._state = found
        return pressed

    def reset(self) -> None:
        self._state = False


# ============================================================
# 旋风 Q/E 数字检测（后台线程）
# ============================================================
class CycloneWatcher:
    """
    Q/E 技能数字检测：图标左上角出现数字（充能数）时回调一次。
    优先模板匹配（已截图生成模板时），否则白色像素兜底。
    """

    def __init__(
        self,
        coords: dict[str, Point],
        templates: dict[str, np.ndarray | None],
        on_trigger: Callable[[str], None],
        logger: Callable[[str], None] | None = None,
        detect_ms: int = CYC_DETECT_MS,
    ) -> None:
        self._coords = coords
        self._templates = templates
        self._on_trigger = on_trigger
        self._logger = logger
        self._detect_ms = detect_ms
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._edges = {key: EdgeTrigger() for key in CYC_DETECT_KEYS}

    def start(self) -> None:
        """启动后台检测线程（幂等）。"""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        for edge in self._edges.values():
            edge.reset()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        """停止后台检测线程。"""
        self._stop.set()

    # --------------------------------------------------------
    # 检测主循环
    # --------------------------------------------------------
    def _log(self, message: str) -> None:
        if self._logger is not None:
            self._logger(message)

    def _detect_one(self, key: str) -> bool | None:
        """
        检测单个键的数字是否出现。
        返回 True/False；截图失败（全黑帧）返回 None 表示保持上次状态。
        """
        point = self._coords.get(key)
        if point is None:
            return None
        origin = window.client_origin()
        if origin is None:
            return None
        template = self._templates.get(key)
        if template is not None:
            # 模板匹配：标定点 ±30px 搜索
            radius = CYC_TEMPLATE_RADIUS
            region = capture_region(
                origin.x + point.x - radius, origin.y + point.y - radius,
                radius * 2, radius * 2,
            )
            return match_template(region, template)
        # 白色像素兜底：标定点为中心 17×19 区域
        region = capture_region(
            origin.x + point.x - CYC_NUM_HW, origin.y + point.y - CYC_NUM_HH,
            CYC_NUM_HW * 2 + 1, CYC_NUM_HH * 2 + 1,
        )
        center = region[CYC_NUM_HH, CYC_NUM_HW]
        found = has_bright_pixel(region)
        # 全黑 = 截图黑帧，视为读取失败：保持上次状态，不误判
        if not found and int(center.max()) == 0 and int(region.max()) == 0:
            return None
        return found

    def _run(self) -> None:
        while not self._stop.is_set():
            for key in CYC_DETECT_KEYS:
                if self._stop.is_set():
                    break
                try:
                    found = self._detect_one(key)
                except Exception as exc:
                    self._log(f"旋风检测 {key.upper()} 异常: {exc}")
                    continue
                if found is None:
                    continue
                if self._edges[key].update(found):
                    self._log(f"旋风检测 {key.upper()} 出现数字，触发按键")
                    self._on_trigger(key)
            self._stop.wait(self._detect_ms / 1000.0)
