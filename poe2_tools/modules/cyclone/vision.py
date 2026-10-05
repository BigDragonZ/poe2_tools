#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
旋风数字识别：Q/E 技能格左上角数字分类（0-6）+ 白/暗双态判定（纯逻辑，可单测）。

渲染态：
- 白色实心（可用/激活）：灰度 > WHITE_THRESHOLD 的亮像素构成数字
- 暗色描边（冷却/消耗中）：数字比背景暗，用「灰度 < 背景亮度(75 分位) - DARK_DELTA」提取

管道（两态共用）：
1. 按态提取二值掩模 → 连通域过滤小噪点，取最大连通域（数字本体）
2. 最大连通域 bbox 加 8% 边距裁剪，归一化缩放到 CANONICAL_SIZE
3. 与对应态模板库逐一求 IoU（实况膨胀 1px 容差，union 用原始掩模）
4. 白/暗两态取置信度高者，≥ match_confidence 才采信，否则视为无数字

模板：templates/cyclone/ 下 white_<d>.png / dark_<d>.png（归一化掩模图），
由 tools.py 从监控样本 sheet 提取；模板与运行 ROI 尺寸无关（bbox 归一化）。

生命 OCR 解析：parse_life_text 为纯函数，OCR 引擎由 engine 层注入。
"""

from __future__ import annotations

import enum
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

logger = logging.getLogger(__name__)

# 白色实心态：灰度阈值（亮像素 = 数字）
WHITE_THRESHOLD = 180
# 暗色描边态：像素灰度低于背景亮度（75 分位）减去该值才算数字
DARK_DELTA = 40
# 连通域最小面积（像素，原生尺度）；过滤椒盐噪点
MIN_COMPONENT_AREA = 8
# bbox 外扩边距比例
_BBOX_MARGIN_RATIO = 0.08
# 归一化尺寸（宽, 高）；模板与实况统一缩放到该尺寸比对
CANONICAL_SIZE = (40, 44)
# 默认匹配置信度（IoU）阈值
DEFAULT_MATCH_CONFIDENCE = 0.5
# 匹配容差：实况膨胀 1px，容忍抗锯齿/亚像素渲染偏移
_DILATE_KERNEL = np.ones((3, 3), np.uint8)


class DigitState(enum.Enum):
    """数字渲染态。"""

    WHITE = "white"  # 白色实心（可用/激活）
    DARK = "dark"    # 暗色描边（冷却/消耗中）


@dataclass
class TemplateLibrary:
    """双态数字模板库：state → {数字: 归一化 0/1 掩模}。"""

    white: dict[int, np.ndarray] = field(default_factory=dict)
    dark: dict[int, np.ndarray] = field(default_factory=dict)

    def templates_for(self, state: DigitState) -> dict[int, np.ndarray]:
        return self.white if state == DigitState.WHITE else self.dark

    def empty(self) -> bool:
        return not self.white and not self.dark


# ============================================================
# 掩模提取与归一化
# ============================================================
def white_mask(roi_bgr: np.ndarray) -> np.ndarray:
    """白色实心态掩模：灰度 > WHITE_THRESHOLD。"""
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    return (gray > WHITE_THRESHOLD).astype(np.uint8)


def dark_mask(roi_bgr: np.ndarray) -> np.ndarray:
    """暗色描边态掩模：灰度显著低于局部背景（75 分位 - DARK_DELTA）。"""
    gray = cv2.cvtColor(roi_bgr, cv2.COLOR_BGR2GRAY)
    background = np.percentile(gray, 75)
    return (gray < background - DARK_DELTA).astype(np.uint8)


def normalize_mask(mask: np.ndarray) -> np.ndarray | None:
    """
    掩模归一化：过滤小连通域噪点，取最大连通域（数字本体），
    bbox 加边距裁剪后缩放到 CANONICAL_SIZE，返回 0/1 矩阵。
    无有效连通域时返回 None。
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    best = -1
    best_area = 0
    for i in range(1, count):
        area = int(stats[i, cv2.CC_STAT_AREA])
        if area >= MIN_COMPONENT_AREA and area > best_area:
            best = i
            best_area = area
    if best < 0:
        return None
    x = int(stats[best, cv2.CC_STAT_LEFT])
    y = int(stats[best, cv2.CC_STAT_TOP])
    w = int(stats[best, cv2.CC_STAT_WIDTH])
    h = int(stats[best, cv2.CC_STAT_HEIGHT])
    component = (labels == best).astype(np.uint8)
    mx = max(1, int(w * _BBOX_MARGIN_RATIO))
    my = max(1, int(h * _BBOX_MARGIN_RATIO))
    x1, y1 = max(0, x - mx), max(0, y - my)
    x2 = min(mask.shape[1], x + w + mx)
    y2 = min(mask.shape[0], y + h + my)
    crop = component[y1:y2, x1:x2]
    resized = cv2.resize(crop, CANONICAL_SIZE, interpolation=cv2.INTER_AREA)
    return (resized > 0.3).astype(np.uint8)


def mask_iou(live: np.ndarray, template: np.ndarray) -> float:
    """
    归一化掩模与模板的匹配度：实况膨胀 1px 后与模板求交，
    union 用原始掩模（膨胀只作命中容差，不放大分母）。
    """
    if live.shape != template.shape:
        return 0.0
    tolerant = cv2.dilate(live, _DILATE_KERNEL, iterations=1)
    inter = int(np.bitwise_and(tolerant, template).sum())
    union = int(np.bitwise_or(live, template).sum())
    return inter / union if union else 0.0


def _best_match(mask: np.ndarray | None, templates: dict[int, np.ndarray]) -> tuple[float, int | None]:
    """在模板库中找最高 IoU；无掩模或空库返回 (0.0, None)。"""
    if mask is None or not templates:
        return 0.0, None
    conf, digit = -1.0, None
    for d, tpl in templates.items():
        score = mask_iou(mask, tpl)
        if score > conf:
            conf, digit = score, d
    return conf, digit


# ============================================================
# 分类入口
# ============================================================
def classify_digit(
    roi_bgr: np.ndarray,
    library: TemplateLibrary,
    match_confidence: float = DEFAULT_MATCH_CONFIDENCE,
) -> tuple[int | None, DigitState | None, float]:
    """
    识别 ROI 中的数字与渲染态。
    返回 (digit, state, conf)；置信度不足或无数字时 digit/state 为 None，
    conf 为两态最高分（供日志排查）。
    """
    if roi_bgr is None or roi_bgr.size == 0 or library.empty():
        return None, None, 0.0
    white_conf, white_digit = _best_match(
        normalize_mask(white_mask(roi_bgr)), library.white
    )
    dark_conf, dark_digit = _best_match(
        normalize_mask(dark_mask(roi_bgr)), library.dark
    )
    if white_conf >= dark_conf and white_conf >= match_confidence:
        return white_digit, DigitState.WHITE, white_conf
    if dark_conf >= match_confidence:
        return dark_digit, DigitState.DARK, dark_conf
    return None, None, max(white_conf, dark_conf)


# ============================================================
# 模板构建与加载
# ============================================================
def build_template(roi_bgr: np.ndarray, state: DigitState) -> np.ndarray | None:
    """从样本 ROI 构建归一化模板掩模（tools/标定流程用）。"""
    mask = white_mask(roi_bgr) if state == DigitState.WHITE else dark_mask(roi_bgr)
    return normalize_mask(mask)


def save_templates(library: TemplateLibrary, directory: Path | str) -> Path:
    """模板库存盘：<dir>/white_<d>.png、dark_<d>.png（0/255 掩模图）。"""
    out = Path(directory)
    out.mkdir(parents=True, exist_ok=True)
    for state, templates in ((DigitState.WHITE, library.white), (DigitState.DARK, library.dark)):
        for digit, mask in templates.items():
            cv2.imwrite(str(out / f"{state.value}_{digit}.png"), mask * 255)
    return out


def load_templates(directory: Path | str) -> TemplateLibrary:
    """
    从目录加载模板库：识别 white_<d>.png / dark_<d>.png 文件名。
    文件损坏或掩模为空的条目跳过；目录不存在返回空库（调用方据此禁用检测）。
    """
    library = TemplateLibrary()
    path = Path(directory)
    if not path.is_dir():
        return library
    for file in sorted(path.glob("*_*.png")):
        stem = file.stem
        try:
            state_name, digit_text = stem.split("_", 1)
            state = DigitState(state_name)
            digit = int(digit_text)
        except (ValueError, KeyError):
            continue
        img = cv2.imread(str(file), cv2.IMREAD_GRAYSCALE)
        if img is None or img.size == 0:
            logger.warning("旋风模板损坏: %s", file)
            continue
        mask = (img > 127).astype(np.uint8)
        if int(mask.sum()) == 0:
            logger.warning("旋风模板无有效像素: %s", file)
            continue
        library.templates_for(state)[digit] = mask
    return library


# ============================================================
# 生命数值文本解析（OCR 结果 → 当前/最大）
# ============================================================
# 分隔符容错：/ \ | l I ；; ：（OCR 易误识别）；数字内允许逗号/句点/空格千分位
_LIFE_PATTERN = re.compile(r"(\d[\d,.\s]*?)\s*[/\\|lI;；:：]\s*(\d[\d,.\s]*)")


def parse_life_text(text: str) -> tuple[int, int] | None:
    """
    解析生命数值文本 "当前/最大"，容错 OCR 千分位逗号/句点/空格与分隔符误识别。
    返回 (cur, max)；无法解析或 max ≤ 0 时返回 None。
    """
    if not text:
        return None
    match = _LIFE_PATTERN.search(text)
    if match is None:
        return None
    cur_text = re.sub(r"\D", "", match.group(1))
    max_text = re.sub(r"\D", "", match.group(2))
    if not cur_text or not max_text:
        return None
    maximum = int(max_text)
    if maximum <= 0:
        return None
    return int(cur_text), maximum
