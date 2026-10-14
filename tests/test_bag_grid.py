#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""背包网格识别单元测试（纯逻辑：线位置聚类 + 晶格拟合 + 覆盖裁剪）。"""

from __future__ import annotations

from poe2_tools.modules.stash.grid import cluster_positions, covered_window, fit_axis


# ============================================================
# 线位置聚类
# ============================================================
def test_cluster_merges_close_positions() -> None:
    """边框厚度/重检产生的相近位置合并为一条（取均值）。"""
    assert cluster_positions([100, 103, 170, 240]) == [102, 170, 240]


def test_cluster_unsorted_input() -> None:
    assert cluster_positions([240, 100, 170]) == [100, 170, 240]


def test_cluster_empty() -> None:
    assert cluster_positions([]) == []


# ============================================================
# 晶格拟合（fit_axis）
# ============================================================
# 实测数据（2560×1440 仓库打开截图）
V_LINES = [1685, 1765, 1835, 1905, 1975, 2046, 2116, 2186, 2256, 2326, 2397, 2467, 2536]
H_LINES = [652, 672, 725, 780, 857, 927, 944, 966, 974, 997, 1024, 1067, 1145, 1168,
           1194, 1244, 1261, 1333, 1345, 1360]


def test_fit_axis_ideal() -> None:
    """理想等距线列：原样拟合。"""
    assert fit_axis([100, 170, 240, 310, 380, 450]) == [100, 170, 240, 310, 380, 450]


def test_fit_axis_real_world_horizontal() -> None:
    """实测水平线（含大量物品噪声线）：拟合出 6 条网格线。"""
    run = fit_axis(H_LINES)
    assert run is not None and run[0] == 780 and len(run) == 6
    assert abs((run[-1] - run[0]) / (len(run) - 1) - 73) < 1


def test_fit_axis_real_world_vertical() -> None:
    """实测垂直线（含面板边框噪声）：拟合出 13 条网格线。"""
    run = fit_axis([1535, *V_LINES, 2551])
    assert run is not None and run == V_LINES


def test_fit_axis_skips_noise_between_cells() -> None:
    """格子中间的噪声线被吸收跳过，不打断 run。"""
    run = fit_axis([100, 130, 170, 240, 300, 310, 380, 450])
    assert run is not None and run[0] == 100 and len(run) == 6


def test_fit_axis_border_thickness_tolerance() -> None:
    """首尾线因边框厚度偏移 ±10 仍可并入 run。"""
    run = fit_axis([95, 170, 240, 310, 380, 455])
    assert run is not None and len(run) == 6


def test_fit_axis_too_few_lines() -> None:
    """线数不足返回 None。"""
    assert fit_axis([100, 170, 240]) is None
    assert fit_axis([]) is None


def test_fit_axis_no_consistent_run() -> None:
    """完全无规律的线位置返回 None。"""
    assert fit_axis([10, 33, 120, 171, 260]) is None


# ============================================================
# 覆盖裁剪（covered_window）：水平线列串线时按竖线覆盖取真实网格
# ============================================================
# 背包竖线只覆盖网格高度（约 775~1140）
V_SPANS = [(775, 1140)] * 13


def test_covered_window_exact() -> None:
    """水平线列正好是网格：原样保留。"""
    h_run = [780, 857, 927, 997, 1067, 1137]
    assert covered_window(h_run, V_SPANS) == h_run


def test_covered_window_trims_chained_lines() -> None:
    """水平线列向上（装备栏）/向下（金币栏装饰）串线：只保留竖线覆盖的网格段。"""
    # 模拟线上实测串线：装备栏 629 起、网格 780~1137、下方装饰 1199/1271/1343
    h_run = [629, 701, 780, 857, 927, 997, 1067, 1137, 1199, 1271, 1343]
    assert covered_window(h_run, V_SPANS) == [780, 857, 927, 997, 1067, 1137]


def test_covered_window_no_coverage() -> None:
    """竖线完全不覆盖：返回 None。"""
    assert covered_window([100, 170, 240, 310], [(500, 600)] * 13) is None


def test_covered_window_partial_verticals() -> None:
    """个别竖线被物品遮挡分段（中点未穿过）：80% 阈值内容忍。"""
    spans = [(775, 1140)] * 11 + [(775, 900)] * 2  # 2 根竖线下半截缺失
    h_run = [780, 857, 927, 997, 1067, 1137]
    assert covered_window(h_run, spans) == h_run


def test_covered_window_edge_inputs() -> None:
    assert covered_window([], V_SPANS) is None
    assert covered_window([780], V_SPANS) is None
    assert covered_window([780, 857], []) is None
