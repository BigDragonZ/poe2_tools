#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
拾取黑框检测：光标 ROI 钳位 + 黑框过滤管道（纯函数，输入 np.ndarray，可单测）。

管道：
1. 以光标为中心取 N×N ROI，边界按屏幕分辨率钳位
2. HSV 黑色掩模（V ≤ black_v_max）
3. 轮廓几何筛选：长宽比 ∈ [2.5, 8.0]，面积 ∈ [150, 6000]
4. Canny 文本密度校验：矩形内部边缘像素占比 ≥ text_density_min
5. 返回距光标最近的黑框中心（屏幕绝对坐标），无候选返回 None
"""

from __future__ import annotations

from typing import Any

import cv2
import numpy as np


def clamp_roi(
    cx: int,
    cy: int,
    roi_size: int,
    resolution: tuple[int, int] | list[int],
) -> tuple[int, int, int, int]:
    """
    以 (cx, cy) 为中心取 roi_size×roi_size 的 ROI，钳位到 [0, W]×[0, H]。
    返回 (x1, y1, x2, y2)；光标贴边时 ROI 自动缩小，不越界。
    """
    width, height = int(resolution[0]), int(resolution[1])
    half = roi_size // 2
    x1 = max(0, cx - half)
    y1 = max(0, cy - half)
    x2 = min(width, cx + half)
    y2 = min(height, cy + half)
    return x1, y1, x2, y2


def black_mask(roi_bgr: np.ndarray, v_max: int) -> np.ndarray:
    """HSV 黑色掩模：V 通道 ≤ v_max 的像素置 255。"""
    hsv = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2HSV)
    return cv2.inRange(hsv[:, :, 2], 0, v_max)


def _passes_geometry(rect_w: int, rect_h: int, area: float, cfg: dict[str, Any]) -> bool:
    """轮廓几何筛选：长宽比与面积。"""
    if rect_h <= 0:
        return False
    ratio = rect_w / rect_h
    if not (cfg["aspect_ratio_min"] <= ratio <= cfg["aspect_ratio_max"]):
        return False
    return bool(cfg["area_min"] <= area <= cfg["area_max"])


def _text_density(roi_gray: np.ndarray, rx: int, ry: int, rw: int, rh: int,
                  canny: list[int]) -> float:
    """矩形内部 Canny 边缘像素占比（文本密度）。"""
    inner = roi_gray[ry : ry + rh, rx : rx + rw]
    if inner.size == 0:
        return 0.0
    edges = cv2.Canny(inner, int(canny[0]), int(canny[1]))
    return float(np.count_nonzero(edges)) / float(inner.size)


def find_loot_box(
    frame_bgr: np.ndarray,
    cursor_x: int,
    cursor_y: int,
    loot_cfg: dict[str, Any],
    resolution: tuple[int, int] | list[int],
) -> tuple[int, int] | None:
    """
    在整帧中检测光标附近的物品黑框。
    返回黑框中心的屏幕绝对坐标，无候选返回 None。
    """
    if frame_bgr is None or frame_bgr.size == 0:
        return None
    x1, y1, x2, y2 = clamp_roi(cursor_x, cursor_y, int(loot_cfg["roi_size"]), resolution)
    if x2 <= x1 or y2 <= y1:
        return None
    roi = frame_bgr[y1:y2, x1:x2]
    mask = black_mask(roi, int(loot_cfg["black_v_max"]))
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    roi_gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    canny = loot_cfg["canny_threshold"]
    density_min = float(loot_cfg["text_density_min"])

    best: tuple[int, int] | None = None
    best_dist = float("inf")
    for contour in contours:
        rx, ry, rw, rh = cv2.boundingRect(contour)
        area = float(cv2.contourArea(contour))
        if not _passes_geometry(rw, rh, area, loot_cfg):
            continue
        if _text_density(roi_gray, rx, ry, rw, rh, canny) < density_min:
            continue
        # 候选中心（屏幕绝对坐标），取距光标最近者
        center = (x1 + rx + rw // 2, y1 + ry + rh // 2)
        dist = (center[0] - cursor_x) ** 2 + (center[1] - cursor_y) ** 2
        if dist < best_dist:
            best_dist = dist
            best = center
    return best
