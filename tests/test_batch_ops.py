#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""批量操作核心单元测试：网格计算、存仓与货币应用流程（假驱动）。"""

from __future__ import annotations

from poe2_tools.config.settings import Point
from poe2_tools.modules import batch_ops
from poe2_tools.modules.batch_ops import apply_currency_to_bag, grid_points, run_dump


class FakeDriver:
    """记录所有调用，不睡觉不点击。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def key_down(self, key: str) -> None:
        self.calls.append(("down", key))

    def key_up(self, key: str) -> None:
        self.calls.append(("up", key))

    def click_client(self, point: Point, button: str = "LButton") -> None:
        self.calls.append(("click", point.x, point.y, button))

    def sleep_ms(self, ms: int) -> None:
        pass


ACTIVE = lambda: True  # noqa: E731
NEVER_STOP = lambda: False  # noqa: E731


# ============================================================
# 网格坐标计算
# ============================================================
def test_grid_points_row_major() -> None:
    points = list(grid_points(Point(100, 200), 50, 2, 3))
    assert [(p.x, p.y) for p in points] == [
        (100, 200), (150, 200), (200, 200),
        (100, 250), (150, 250), (200, 250),
    ]


def test_grid_points_fractional_cell_rounds() -> None:
    points = list(grid_points(Point(0, 0), 52.6, 1, 3))
    assert [(p.x, p.y) for p in points] == [(0, 0), (53, 0), (105, 0)]


# ============================================================
# 一键存仓
# ============================================================
def test_run_dump_clicks_all_cells_with_ctrl() -> None:
    driver = FakeDriver()
    aborted = run_dump(Point(10, 20), 50, 2, 2, 30, NEVER_STOP, ACTIVE, driver)
    assert aborted is False
    assert driver.calls[0] == ("down", "Ctrl")
    assert driver.calls[-1] == ("up", "Ctrl")
    clicks = [c for c in driver.calls if c[0] == "click"]
    assert [(c[1], c[2]) for c in clicks] == [(10, 20), (60, 20), (10, 70), (60, 70)]
    assert all(c[3] == "LButton" for c in clicks)


def test_run_dump_stop_releases_ctrl() -> None:
    driver = FakeDriver()
    clicks_before_stop = 1
    state = {"n": 0}

    def should_stop() -> bool:
        return state["n"] >= clicks_before_stop

    orig_click = driver.click_client

    def counting_click(point: Point, button: str = "LButton") -> None:
        state["n"] += 1
        orig_click(point, button)

    driver.click_client = counting_click  # type: ignore[method-assign]
    aborted = run_dump(Point(0, 0), 50, 5, 11, 30, should_stop, ACTIVE, driver)
    assert aborted is True
    assert driver.calls[-1] == ("up", "Ctrl")


def test_run_dump_aborts_when_window_inactive() -> None:
    driver = FakeDriver()
    aborted = run_dump(Point(0, 0), 50, 5, 11, 30, NEVER_STOP, lambda: False, driver)
    assert aborted is True
    assert [c for c in driver.calls if c[0] == "click"] == []
    assert driver.calls[-1] == ("up", "Ctrl")


# ============================================================
# 货币批量应用
# ============================================================
def test_apply_currency_sequence() -> None:
    driver = FakeDriver()
    aborted = apply_currency_to_bag(
        Point(80, 240), 2, Point(10, 20), 50, 1, 2, 50, NEVER_STOP, ACTIVE, driver
    )
    assert aborted is False
    assert driver.calls[0] == ("down", "Shift")
    assert driver.calls[1] == ("click", 80, 240, "RButton")  # 右键选中货币
    assert driver.calls[-1] == ("up", "Shift")
    clicks = [c for c in driver.calls if c[0] == "click" and c[3] == "LButton"]
    # 每格 2 次：格(10,20)×2 + 格(60,20)×2
    assert [(c[1], c[2]) for c in clicks] == [(10, 20), (10, 20), (60, 20), (60, 20)]


def test_apply_currency_abort_releases_shift() -> None:
    driver = FakeDriver()
    aborted = apply_currency_to_bag(
        Point(80, 240), 1, Point(10, 20), 50, 5, 11, 50, lambda: True, ACTIVE, driver
    )
    assert aborted is True
    assert driver.calls[-1] == ("up", "Shift")
