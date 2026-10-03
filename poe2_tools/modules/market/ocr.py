#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
OCR 引擎封装（懒加载，可注入替身）。

默认使用 rapidocr_onnxruntime（含中英文模型，无需外部进程）；
识别结果统一为带检测框中心坐标的文本块列表，供 parser 做行列重建。
rapidocr 不是硬依赖：未安装时在首次识别时抛出 OcrEngineError，
扫描器与测试可注入任何实现 recognize(image) -> list[str] 的对象。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from poe2_tools.modules.market.parser import TextBlock

if TYPE_CHECKING:
    from PIL import Image


class OcrEngineError(Exception):
    """OCR 引擎不可用或识别失败（中文原因，直接展示给用户）。"""


class OcrEngine(Protocol):
    """OCR 引擎协议：图像 → 带坐标的文本块列表。"""

    def recognize_blocks(self, image: "Image.Image") -> list[TextBlock]:
        ...


class RapidOcrEngine:
    """RapidOCR 引擎：首次使用时加载模型（懒初始化，线程内复用）。"""

    def __init__(self) -> None:
        self._engine = None

    def _ensure_engine(self):
        if self._engine is not None:
            return self._engine
        try:
            from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415 懒导入
        except ImportError as e:
            raise OcrEngineError(
                "未安装 OCR 引擎：请执行 uv add rapidocr-onnxruntime 后重试"
            ) from e
        self._engine = RapidOCR()
        return self._engine

    def recognize_blocks(self, image: "Image.Image") -> list[TextBlock]:
        """识别图像文本，返回带检测框中心坐标的文本块（供行列重建）。"""
        import numpy as np  # noqa: PLC0415 随 opencv 依赖提供，懒导入

        engine = self._ensure_engine()
        try:
            result, _ = engine(np.asarray(image.convert("RGB")))
        except Exception as e:
            raise OcrEngineError(f"OCR 识别失败：{e}") from e
        if not result:
            return []
        blocks: list[TextBlock] = []
        for box, text, _score in result:
            xs = [p[0] for p in box]
            ys = [p[1] for p in box]
            blocks.append(TextBlock(
                text=str(text),
                cx=sum(xs) / len(xs),
                cy=sum(ys) / len(ys),
                h=max(ys) - min(ys),
            ))
        return blocks
