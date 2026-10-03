#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
开发页测量：收集开发阶段需要的坐标与范围。

- 测量坐标：复用坐标模块的标定流程（界面点「测量」→ 游戏内 F5 记录光标
  客户区坐标），由 app 控制器处理，本模块不涉及
- 框选范围：界面点「框选」开启 RangeMarkSession，挂鼠标左键钩子
  （mouse 库，仅 POE2 前台时计数），按下记一角、抬起记另一角，
  两点经 normalize_range 规范化为 (x1, y1, x2, y2)

会话只挂一次左键钩子，完成/取消时精确 unhook，不影响其他模块。
mouse 懒导入，纯逻辑不依赖桌面环境。
"""

from __future__ import annotations

from collections.abc import Callable

from poe2_tools.config.settings import Point
from poe2_tools.core import window

# 范围最小尺寸（像素）：小于此视为误触（如单击），本次框选作废
MIN_RANGE_W = 4
MIN_RANGE_H = 4


class MeasureError(Exception):
    """测量失败（中文原因，直接展示给用户）。"""


# ============================================================
# 纯逻辑：两点 → 范围（可单测）
# ============================================================
def normalize_range(
    p1: Point,
    p2: Point,
    size: Point | None = None,
) -> tuple[int, int, int, int]:
    """
    按下/抬起两点（客户区坐标）规范化为范围 (x1, y1, x2, y2)：
    任意拖拽方向均可（min/max 排序），提供客户区尺寸时钳位到区内。
    范围小于最小尺寸时抛 MeasureError。
    """
    x1, x2 = sorted((p1.x, p2.x))
    y1, y2 = sorted((p1.y, p2.y))
    if size is not None:
        x1 = max(0, min(x1, size.x))
        x2 = max(0, min(x2, size.x))
        y1 = max(0, min(y1, size.y))
        y2 = max(0, min(y2, size.y))
    if x2 - x1 < MIN_RANGE_W or y2 - y1 < MIN_RANGE_H:
        raise MeasureError(
            f"框选范围太小（{x2 - x1}×{y2 - y1}，至少 {MIN_RANGE_W}×{MIN_RANGE_H}）："
            f"请按住左键拖出一个矩形后松开"
        )
    return x1, y1, x2, y2


# ============================================================
# 左键框选会话（「框选」按钮启动）
# ============================================================
class RangeMarkSession:
    """
    左键框选会话：begin 挂钩子，左键按下记第一角、抬起记第二角并回调
    on_done(p1, p2)（鼠标钩子线程）。cancel 精确解绑钩子；会话不自动重入。
    钩子不拦截按键，拖拽会照常传入游戏，仅作旁观记录。
    """

    def __init__(
        self,
        on_log: Callable[[str], None],
        on_done: Callable[[Point, Point], None],
    ) -> None:
        self._on_log = on_log
        self._on_done = on_done
        self._hooks: list[Callable[[object], None]] = []
        self._press: Point | None = None

    @property
    def active(self) -> bool:
        return bool(self._hooks)

    def begin(self) -> None:
        """挂左键钩子开始框选；已激活时重置按下点后继续。"""
        import mouse  # noqa: PLC0415 框选期才需要全局鼠标钩子

        self._press = None
        if not self._hooks:
            self._hooks = [
                mouse.on_button(self._on_left_down, buttons=("left",), types=("down",)),
                mouse.on_button(self._on_left_up, buttons=("left",), types=("up",)),
            ]

    def cancel(self) -> None:
        """取消框选并解绑钩子（幂等）。"""
        if not self._hooks:
            return
        import mouse  # noqa: PLC0415

        for hook in self._hooks:
            try:
                mouse.unhook(hook)
            except Exception:
                pass
        self._hooks = []
        self._press = None

    def _on_left_down(self) -> None:
        """左键按下（钩子线程）：仅 POE2 前台时记录第一角。"""
        if not window.is_poe_active():
            return
        pos = window.cursor_client_pos()
        if pos is None:
            return
        self._press = pos

    def _on_left_up(self) -> None:
        """左键抬起（钩子线程）：有按下点则配对成一次框选。"""
        if self._press is None:
            return
        if not window.is_poe_active():
            self._press = None
            return
        pos = window.cursor_client_pos()
        press, self._press = self._press, None
        if pos is None:
            return
        self.cancel()
        self._on_done(press, pos)
