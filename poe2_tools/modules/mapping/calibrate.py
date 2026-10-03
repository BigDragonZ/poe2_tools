#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
刷图 Q=6 区域标定：F5 进入标记模式后，鼠标右键先后点击检测数字的
左上角与右下角，两点构成的矩形即检测 ROI。

流程（旋风页「标定 Q=6」→ 游戏内 F5 触发）：
1. Q6MarkSession 挂鼠标右键钩子（mouse 库，仅 POE2 前台时计数）：
   第 1 次右键 = 左上角，第 2 次右键 = 右下角，记录客户区坐标
2. normalize_roi（纯逻辑，可单测）：两点规范化（min/max 排序、
   钳位到客户区、校验最小尺寸）为 (x1, y1, x2, y2)
3. capture_template：按 ROI 截图存 templates/q6.png 作检测模板；
   ROI 交调用方写入 ini [Mapping] q6_roi

标记会话只挂一次右键钩子，完成/取消时精确 unhook，不影响其他模块。
mss/mouse 懒导入，纯逻辑不依赖桌面环境。
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import cv2

from poe2_tools.config.settings import Point
from poe2_tools.core import window

# ROI 最小尺寸（像素）：小于此视为误触，标定失败
MIN_ROI_W = 6
MIN_ROI_H = 6

# 模板输出（相对仓库根目录）
REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
Q6_TEMPLATE_PATH = REPO_ROOT / "templates" / "q6.png"


class CalibrateError(Exception):
    """标定失败（中文原因，直接展示给用户）。"""


# ============================================================
# 纯逻辑：两点 → ROI（可单测）
# ============================================================
def normalize_roi(
    p1: Point,
    p2: Point,
    size: Point | None = None,
) -> tuple[int, int, int, int]:
    """
    两个角点（客户区坐标）规范化为 ROI (x1, y1, x2, y2)：
    任意点击顺序均可（min/max 排序），提供客户区尺寸时钳位到区内。
    区域小于最小尺寸时抛 CalibrateError。
    """
    x1, x2 = sorted((p1.x, p2.x))
    y1, y2 = sorted((p1.y, p2.y))
    if size is not None:
        x1 = max(0, min(x1, size.x))
        x2 = max(0, min(x2, size.x))
        y1 = max(0, min(y1, size.y))
        y2 = max(0, min(y2, size.y))
    if x2 - x1 < MIN_ROI_W or y2 - y1 < MIN_ROI_H:
        raise CalibrateError(
            f"标记区域太小（{x2 - x1}×{y2 - y1}，至少 {MIN_ROI_W}×{MIN_ROI_H}）："
            f"请右键分别点击数字的左上角与右下角"
        )
    return x1, y1, x2, y2


# ============================================================
# 模板截图（I/O，第二次右键后调用）
# ============================================================
def capture_template(roi: tuple[int, int, int, int]) -> None:
    """按客户区 ROI 截图存 templates/q6.png 作检测模板；失败抛 CalibrateError。"""
    import mss  # noqa: PLC0415 懒导入，避免纯逻辑路径依赖截图库

    import numpy as np  # noqa: PLC0415

    origin = window.client_origin()
    if origin is None:
        raise CalibrateError("未找到 POE2 窗口")
    x1, y1, x2, y2 = roi
    with mss.mss() as sct:
        shot = sct.grab({
            "left": origin.x + x1, "top": origin.y + y1,
            "width": x2 - x1, "height": y2 - y1,
        })
        image = np.array(shot)[:, :, :3]  # BGRA -> BGR
    Q6_TEMPLATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(Q6_TEMPLATE_PATH), image)


# ============================================================
# 右键两角标记会话（F5 回调启动）
# ============================================================
class Q6MarkSession:
    """
    右键两角标记会话：begin 挂钩子，第一次右键记左上角，
    第二次右键记右下角并回调 on_done(p1, p2)（鼠标钩子线程）。
    cancel 精确解绑钩子；会话不自动重入。
    """

    def __init__(
        self,
        on_log: Callable[[str], None],
        on_done: Callable[[Point, Point], None],
    ) -> None:
        self._on_log = on_log
        self._on_done = on_done
        self._hook: Callable[[object], None] | None = None
        self._first: Point | None = None

    @property
    def active(self) -> bool:
        return self._hook is not None

    def begin(self) -> None:
        """挂右键钩子开始标记；已激活时重置第一点后继续。"""
        import mouse  # noqa: PLC0415 标记期才需要全局鼠标钩子

        self._first = None
        if self._hook is None:
            self._hook = mouse.on_button(
                self._on_right_down, buttons=("right",), types=("down",)
            )

    def cancel(self) -> None:
        """取消标记并解绑钩子（幂等）。"""
        if self._hook is None:
            return
        import mouse  # noqa: PLC0415

        try:
            mouse.unhook(self._hook)
        except Exception:
            pass
        self._hook = None
        self._first = None

    def _on_right_down(self) -> None:
        """右键回调（钩子线程）：仅 POE2 前台时计数。"""
        if not window.is_poe_active():
            return
        pos = window.cursor_client_pos()
        if pos is None:
            return
        if self._first is None:
            self._first = pos
            self._on_log(f"Q6 标记：左上角已记录 ({pos.x}, {pos.y})，请右键点击数字右下角")
            return
        first, self._first = self._first, None
        self.cancel()
        self._on_done(first, pos)
