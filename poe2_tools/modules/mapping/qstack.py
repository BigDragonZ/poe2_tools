#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Q 层数（=6）识别：F5 + 右键两角标记的检测区域 + 二值点阵比对。

- 模板：旋风页「标定 Q=6」流程生成的 templates/q6.png（标记区域截图），
  用 load_mask 二值化为点阵掩模
- ROI：ini [Mapping] q6_roi（客户区坐标）+ client_origin() 换算屏幕坐标，
  由 q6_roi_screen 计算；运行时 ROI 与模板同尺寸，逐帧二值化比对
- 判定：掩模亮像素命中比例（实况膨胀 1px 容差）≥ match_confidence 判定 Q 已满
- 比对逻辑为纯函数（输入 np.ndarray，可单测）；未标定/无模板时调用方
  禁用 COMBOS 检测（不崩溃）
"""

from __future__ import annotations

import logging
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 自适应二值化参数（局部均值阈值，块大小与常数）
_ADAPTIVE_BLOCK = 11
_ADAPTIVE_C = 2

# 全局对比度下限：自适应阈值在均匀暗区会把整个背景误判为亮，
# ROI 灰度极差不足时视为「无数字」，返回空矩阵
_MIN_CONTRAST = 40

# 匹配容差：实况二值图先膨胀 1px 再与掩模比对，容忍抗锯齿/亚像素渲染
# 造成的 1px 内偏移（1px 偏移会让逐像素比对掉到 0.7，数字形状区分度不受影响）
_DILATE_KERNEL = np.ones((3, 3), np.uint8)


def binarize_roi(roi_bgr: np.ndarray) -> np.ndarray:
    """
    ROI 自适应局部二值化，剥离 CD 扇形阴影。
    返回 0/1 的 uint8 矩阵（亮像素 = 1，数字为亮色）；
    对比度不足（无数字）时返回全 0。
    """
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    if int(gray.max()) - int(gray.min()) < _MIN_CONTRAST:
        return np.zeros(gray.shape, dtype=np.uint8)
    binary = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, cv2.THRESH_BINARY,
        _ADAPTIVE_BLOCK, _ADAPTIVE_C,
    )
    return (binary > 0).astype(np.uint8)


def mask_confidence(binary: np.ndarray, mask: np.ndarray) -> float:
    """
    二值矩阵与掩模的匹配度：掩模亮像素命中比例（容差 1px）。
    binary（实况）先膨胀 1px 再与掩模求交，容忍亚像素渲染偏移；
    binary、mask 均为同尺寸 0/1 矩阵；掩模为空（无亮像素）返回 0.0。
    """
    if binary.shape != mask.shape:
        return 0.0
    total = int(mask.sum())
    if total == 0:
        return 0.0
    tolerant = cv2.dilate(binary, _DILATE_KERNEL, iterations=1)
    hit = int(np.bitwise_and(tolerant, mask).sum())
    return hit / total


def is_q_full(
    roi_bgr: np.ndarray,
    mask: np.ndarray | None,
    confidence: float = 0.92,
) -> bool:
    """Q 层数是否满 6：实时 ROI 二值化后与掩模比对。无掩模时返回 False。"""
    if mask is None or roi_bgr is None or roi_bgr.size == 0:
        return False
    return mask_confidence(binarize_roi(roi_bgr), mask) >= confidence


# ============================================================
# Q6 模板与 ROI（F5 + 右键两角标记生成 templates/q6.png + ini [Mapping] q6_roi）
# ============================================================
def load_mask(template_path: Path | str) -> np.ndarray | None:
    """
    加载检测模板截图并二值化为点阵掩模。
    文件缺失/损坏/二值化后无亮像素时返回 None（调用方据此禁用 COMBOS）。
    """
    path = Path(template_path)
    if not path.exists():
        return None
    img = cv2.imread(str(path))
    if img is None or img.size == 0:
        logger.warning("Q6 模板损坏: %s", path)
        return None
    mask = binarize_roi(img)
    if int(mask.sum()) == 0:
        logger.warning("Q6 模板二值化后无亮像素（可能截图无数字）: %s", path)
        return None
    return mask


def q6_roi_screen(
    origin_x: int,
    origin_y: int,
    roi_box: tuple[int, int, int, int],
) -> tuple[int, int, int, int]:
    """ini [Mapping] q6_roi（客户区坐标）→ 屏幕坐标 ROI。"""
    return (
        origin_x + roi_box[0],
        origin_y + roi_box[1],
        origin_x + roi_box[2],
        origin_y + roi_box[3],
    )
