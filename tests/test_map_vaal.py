#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""瓦地图单元测试：物品文本解析、打造决策、取图/打造/存回流程（假驱动）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from poe2_tools.config.settings import Point, Settings
from poe2_tools.modules import map_vaal
from poe2_tools.modules.map_vaal import (
    MapVaalRunner,
    classify,
    craft_action,
    needs_craft,
    page_button,
    parse_waystone,
    tier_button,
    vaal_ready,
)

FIXTURES = Path(__file__).parent / "fixtures" / "map_vaal"


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def make_text(
    rarity: str = "稀有",
    affixes: int = 4,
    corrupted: bool = False,
    tier: int = 15,
    item_rarity: int | None = None,
    monster_effect: int | None = None,
) -> str:
    """合成换界石文本（解析只关心种类/稀有度/阶级/词缀头/汙染标记/头部数值）。"""
    lines = ["物品種類: 換界石", f"稀有度: {rarity}", "測試 刀鋒", f"換界石（階級 {tier}）", "--------"]
    if item_rarity is not None:
        lines.append(f"物品稀有度: +{item_rarity}% (augmented)")
    if monster_effect is not None:
        lines.append(f"怪物效能: +{monster_effect}% (augmented)")
    if item_rarity is not None or monster_effect is not None:
        lines.append("--------")
    for _ in range(affixes):
        lines.append('{ 前綴 "測試的"(階層：1) }')
        lines.append("詞綴內容")
    if corrupted:
        lines += ["--------", "已汙染"]
    return "\r\n".join(lines)


# ============================================================
# 物品文本解析（真实样本来自游戏内 Ctrl+C）
# ============================================================
def test_parse_white_waystone() -> None:
    info = parse_waystone(_fixture("white.txt"))
    assert info is not None
    assert info.tier == 15
    assert info.affixes == 0
    assert info.corrupted is False
    assert info.is_rare is False


def test_parse_magic_waystone() -> None:
    info = parse_waystone(_fixture("magic2.txt"))
    assert info is not None
    assert info.affixes == 2
    assert info.rarity.startswith("魔法")
    assert info.corrupted is False


def test_parse_rare_waystone_multi_line_affix() -> None:
    # rare5 样本含一条两行词缀，词缀数按 { 前綴/後綴 } 头计数而非行数
    info = parse_waystone(_fixture("rare5.txt"))
    assert info is not None
    assert info.affixes == 5
    assert info.is_rare
    assert info.corrupted is False


def test_parse_corrupted_waystone() -> None:
    info = parse_waystone(_fixture("corrupted.txt"))
    assert info is not None
    assert info.corrupted is True
    assert info.affixes == 4
    # 真实样本头部数值行：物品稀有度 +14%、怪物效能 +16%
    assert info.item_rarity_pct == 14
    assert info.monster_effect_pct == 16
    assert classify(info, 100) == "normal"  # 14+16 < 100 且非 T16/8 词


def test_parse_rejects_non_waystone() -> None:
    assert parse_waystone(_fixture("currency.txt")) is None
    assert parse_waystone(None) is None
    assert parse_waystone("") is None


# ============================================================
# 过滤与打造决策
# ============================================================
def test_needs_craft() -> None:
    assert needs_craft(parse_waystone(make_text(affixes=0)))  # 白图
    assert needs_craft(parse_waystone(make_text(affixes=5)))  # 未满 6 词
    assert not needs_craft(parse_waystone(make_text(affixes=6)))  # 已满 6 词
    assert not needs_craft(parse_waystone(make_text(affixes=4, corrupted=True)))  # 已汙染


def test_craft_action() -> None:
    # 打造阶段只出点金/崇高，不含瓦尔
    assert craft_action(parse_waystone(make_text(rarity="普通", affixes=0))) == "alch"
    assert craft_action(parse_waystone(make_text(rarity="魔法", affixes=2))) == "alch"
    assert craft_action(parse_waystone(make_text(rarity="稀有", affixes=5))) == "ex"
    assert craft_action(parse_waystone(make_text(rarity="稀有", affixes=6))) is None
    assert craft_action(parse_waystone(make_text(affixes=6, corrupted=True))) is None


def test_vaal_ready() -> None:
    assert vaal_ready(parse_waystone(make_text(rarity="稀有", affixes=6)))
    assert not vaal_ready(parse_waystone(make_text(rarity="稀有", affixes=5)))
    assert not vaal_ready(parse_waystone(make_text(rarity="魔法", affixes=6)))
    assert not vaal_ready(parse_waystone(make_text(affixes=6, corrupted=True)))


# ============================================================
# 瓦后分类（优先级：T16 → 数值达标 → 8 词 → 其他）
# ============================================================
def test_classify_priority() -> None:
    # T16 优先级最高（数值再高也直接归 t16）
    t16 = parse_waystone(make_text(tier=16, affixes=8, item_rarity=80, monster_effect=40))
    assert classify(t16, 100) == "t16"
    # 物品稀有度+怪物效能 ≥ 阈值 → map100（数值盖过 8 词）
    rich = parse_waystone(make_text(affixes=8, item_rarity=60, monster_effect=40))
    assert classify(rich, 100) == "map100"
    # 恰好等于阈值也算达标
    edge = parse_waystone(make_text(affixes=6, item_rarity=50, monster_effect=50))
    assert classify(edge, 100) == "map100"
    # 8 词但数值不够 → advanced
    eight = parse_waystone(make_text(affixes=8, item_rarity=30, monster_effect=20))
    assert classify(eight, 100) == "advanced"
    # 其他 → normal
    plain = parse_waystone(make_text(affixes=6, item_rarity=10, monster_effect=5))
    assert classify(plain, 100) == "normal"
    # 缺数值行按 0 处理
    bare = parse_waystone(make_text(affixes=6))
    assert classify(bare, 100) == "normal"


def test_parse_waystone_stat_values() -> None:
    info = parse_waystone(make_text(item_rarity=14, monster_effect=16))
    assert info is not None
    assert info.item_rarity_pct == 14
    assert info.monster_effect_pct == 16
    info = parse_waystone(make_text())
    assert info is not None
    assert info.item_rarity_pct == 0 and info.monster_effect_pct == 0


# ============================================================
# 仓库界面坐标
# ============================================================
def test_tier_button() -> None:
    s = Settings()
    assert tier_button(s.stash_ui, 1) == Point(82, 171)
    assert tier_button(s.stash_ui, 8) == Point(549, 171)
    assert tier_button(s.stash_ui, 9) == Point(82, 233)
    assert tier_button(s.stash_ui, 15) == Point(482, 233)
    assert tier_button(s.stash_ui, 16) == Point(549, 233)


def test_page_button() -> None:
    s = Settings()
    assert page_button(s.stash_ui, 1) == Point(175, 304)
    assert page_button(s.stash_ui, 6) == Point(175 + 5 * 57, 304)


# ============================================================
# 流程（假驱动）
# ============================================================
class FakeDriver:
    """记录点击序列；texts 模拟各坐标格子的物品文本（ctrl_click 后视为已移走）。"""

    def __init__(self, texts: dict[tuple[int, int], str | None]) -> None:
        self.calls: list[tuple] = []
        self.texts = dict(texts)
        self.remove_on_ctrl_click = True

    def click_client(self, point: Point, button: str = "LButton") -> None:
        self.calls.append(("click", point.x, point.y, button))

    def ctrl_click_client(self, point: Point) -> None:
        self.calls.append(("ctrl_click", point.x, point.y))
        if self.remove_on_ctrl_click:
            self.texts[(point.x, point.y)] = None

    def ctrl_shift_click_client(self, point: Point) -> None:
        self.calls.append(("ctrl_shift_click", point.x, point.y))
        if self.remove_on_ctrl_click:
            self.texts[(point.x, point.y)] = None

    def read_item(self, point: Point) -> str | None:
        self.calls.append(("read", point.x, point.y))
        return self.texts.get((point.x, point.y))

    def occupied_cells(self, origin: Point, cell: float, rows: int, cols: int) -> set[tuple[int, int]]:
        """与真实驱动一致：按网格坐标查 texts，有文本的格子视为占用。"""
        result = set()
        for row in range(rows):
            for col in range(cols):
                key = (round(origin.x + col * cell), round(origin.y + row * cell))
                if self.texts.get(key):
                    result.add((row, col))
        return result

    def sleep_ms(self, ms: int) -> None:
        pass

    def stash_open(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _poe_active(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(map_vaal.window, "is_poe_active", lambda: True)


def _runner(settings: Settings) -> MapVaalRunner:
    return MapVaalRunner(settings)


def _small_stash_settings() -> Settings:
    """2×2 仓库格、单页的小布局，便于断言坐标。"""
    s = Settings()
    s.stash_ui.stash_grid_origin = Point(0, 0)
    s.stash_ui.stash_grid_cell = 65
    s.stash_ui.stash_grid_rows = 2
    s.stash_ui.stash_grid_cols = 2
    s.stash_ui.page_count = 1
    return s


def test_pull_phase_filters_corrupted_and_full() -> None:
    s = _small_stash_settings()
    texts = {
        (0, 0): make_text(affixes=5),                     # 未满 6 词 → 取
        (65, 0): make_text(affixes=4, corrupted=True),    # 已汙染 → 留
        (0, 65): make_text(affixes=6),                    # 满 6 词 → 留
        (65, 65): None,                                   # 空格
    }
    driver = FakeDriver(texts)
    pulled, aborted = _runner(s)._pull_phase(driver, Point(1000, 800))
    assert (pulled, aborted) == (1, False)
    ctrl_clicks = [c for c in driver.calls if c[0] == "ctrl_click"]
    assert [(c[1], c[2]) for c in ctrl_clicks] == [(0, 0)]
    # 依次点 Map 标签 → 阶级按钮 → 第 1 页，单页不再翻页
    clicks = [c for c in driver.calls if c[0] == "click"]
    assert clicks[0][1:3] == (s.stash_ui.tab_map.x, s.stash_ui.tab_map.y)
    assert clicks[1][1:3] == (482, 233)
    assert clicks[2][1:3] == (175, 304)
    assert len(clicks) == 3


def test_pull_phase_capacity_limit() -> None:
    # 背包可用格 = 行×列（最左列保留）：1×2=2，3 张待瓦图只取 2 张
    s = _small_stash_settings()
    s.general.sort.rows = 1
    s.general.sort.cols = 2
    texts = {
        (0, 0): make_text(affixes=0),
        (65, 0): make_text(affixes=5),
        (0, 65): make_text(affixes=4),
    }
    driver = FakeDriver(texts)
    pulled, aborted = _runner(s)._pull_phase(driver, Point(1000, 800))
    assert (pulled, aborted) == (2, False)
    ctrl_clicks = [c for c in driver.calls if c[0] == "ctrl_click"]
    assert [(c[1], c[2]) for c in ctrl_clicks] == [(0, 0), (65, 0)]  # 第 3 张不再取


def test_pull_phase_skips_empty_pages() -> None:
    # 两页都没有地图：整页跳过、零读取，只点 标签→阶级→第1页→第2页
    s = _small_stash_settings()
    s.stash_ui.page_count = 2
    driver = FakeDriver({})
    pulled, aborted = _runner(s)._pull_phase(driver, Point(1000, 800))
    assert (pulled, aborted) == (0, False)
    assert [c for c in driver.calls if c[0] == "read"] == []
    clicks = [c for c in driver.calls if c[0] == "click"]
    assert [c[1:3] for c in clicks] == [
        (s.stash_ui.tab_map.x, s.stash_ui.tab_map.y),
        (482, 233),
        (175, 304),  # 第 1 页
        (232, 304),  # 第 2 页
    ]


def test_pull_phase_extracts_unidentified_from_bag_first() -> None:
    # 阶段零：背包里的未鉴定地图在点阶级按钮前被取出
    s = _small_stash_settings()
    s.general.sort.cell_size = 70
    bag_cell = (1000, 800)
    texts = {
        bag_cell: make_text(affixes=0) + "\r\n--------\r\n未鑑定",
        (0, 0): make_text(affixes=5),
    }
    driver = FakeDriver(texts)
    pulled, _ = _runner(s)._pull_phase(driver, Point(*bag_cell))
    assert pulled == 1
    ctrl_clicks = [c for c in driver.calls if c[0] == "ctrl_click"]
    assert ctrl_clicks[0][1:3] == bag_cell  # 先取背包未鉴定图
    tier_click_at = next(i for i, c in enumerate(driver.calls) if c == ("click", 482, 233, "LButton"))
    extract_at = driver.calls.index(ctrl_clicks[0])
    assert extract_at < tier_click_at


def test_pull_phase_skips_unidentified_in_stash() -> None:
    # 仓库里的未鉴定地图不取（读不到词缀，无法过滤）
    s = _small_stash_settings()
    texts = {(0, 0): make_text(affixes=0) + "\r\n--------\r\n未鑑定"}
    driver = FakeDriver(texts)
    pulled, aborted = _runner(s)._pull_phase(driver, Point(1000, 800))
    assert (pulled, aborted) == (0, False)
    assert [c for c in driver.calls if c[0] == "ctrl_click"] == []


def test_pull_phase_bag_full_stops() -> None:
    s = _small_stash_settings()
    texts = {(0, 0): make_text(affixes=0), (65, 0): make_text(affixes=5)}
    driver = FakeDriver(texts)
    driver.remove_on_ctrl_click = False  # 模拟背包已满：取图后格子未空
    pulled, aborted = _runner(s)._pull_phase(driver, Point(1000, 800))
    assert (pulled, aborted) == (0, False)
    assert len([c for c in driver.calls if c[0] == "ctrl_click"]) == 1  # 立即停止
    assert len([c for c in driver.calls if c[0] == "read"]) == 2  # 首次读取 + 取图校验


def _craft_settings() -> Settings:
    s = Settings()
    s.general.sort.rows = 1
    s.general.sort.cols = 2
    s.general.sort.cell_size = 70
    s.currency["alch"] = Point(340, 240)
    s.currency["ex"] = Point(68, 500)
    s.currency["vaal"] = Point(425, 240)
    return s


class ScriptedDriver(FakeDriver):
    """read_item 按队列依次出文本（模拟货币应用后的状态变化）。"""

    def __init__(self, scripts: dict[tuple[int, int], list[str | None]]) -> None:
        super().__init__({})
        self.scripts = {k: list(v) for k, v in scripts.items()}

    def read_item(self, point: Point) -> str | None:
        self.calls.append(("read", point.x, point.y))
        queue = self.scripts.get((point.x, point.y), [])
        return queue.pop(0) if queue else None

    def occupied_cells(self, origin: Point, cell: float, rows: int, cols: int) -> set[tuple[int, int]]:
        result = set()
        for row in range(rows):
            for col in range(cols):
                key = (round(origin.x + col * cell), round(origin.y + row * cell))
                if self.scripts.get(key):
                    result.add((row, col))
        return result


def test_craft_phase_white_map_full_sequence() -> None:
    # 打造阶段只补满 6 词，不瓦尔：白图 → 点金(4词) → 崇高×2(6词)
    s = _craft_settings()
    origin = Point(1000, 800)
    cell = (1000, 800)
    white = make_text(rarity="普通", affixes=0)
    driver = ScriptedDriver({
        cell: [white,
               make_text(affixes=4),   # 点金后
               make_text(affixes=5),   # 崇高后
               make_text(affixes=6)],  # 崇高后
    })
    done, aborted = _runner(s)._craft_phase(driver, origin)
    assert (done, aborted) == (1, False)
    clicks = [c for c in driver.calls if c[0] == "click"]
    # 首个点击 = 切通货页，其后：点金右键→格左键，崇高右键→格左键 ×2；无瓦尔
    assert clicks[0][1:3] == (s.stash_ui.tab_currency.x, s.stash_ui.tab_currency.y)
    assert clicks[1:] == [
        ("click", 340, 240, "RButton"), ("click", 1000, 800, "LButton"),
        ("click", 68, 500, "RButton"), ("click", 1000, 800, "LButton"),
        ("click", 68, 500, "RButton"), ("click", 1000, 800, "LButton"),
    ]


def test_top_up_gives_up_when_currency_no_effect() -> None:
    s = _craft_settings()
    rare5 = make_text(affixes=5)
    driver = ScriptedDriver({(100, 200): [rare5, rare5]})  # 崇高始终无变化
    info = parse_waystone(rare5)
    final, aborted = _runner(s)._top_up(driver, Point(100, 200), info)
    assert (final, aborted) == (None, False)
    clicks = [c for c in driver.calls if c[0] == "click"]
    assert ("click", 425, 240, "RButton") not in clicks  # 打造阶段不碰瓦尔
    assert len([c for c in clicks if c[1:3] == (68, 500)]) == 2  # 两次无变化即放弃


def test_check_phase_tops_up_stragglers() -> None:
    # 瓦前检查：一张已满 6 词直接通过，一张 5 词补一颗崇高后通过
    s = _craft_settings()
    origin = Point(1000, 800)
    driver = ScriptedDriver({
        (1000, 800): [make_text(affixes=6)],
        (1070, 800): [make_text(affixes=5), make_text(affixes=6)],
    })
    ready, aborted = _runner(s)._check_phase(driver, origin)
    assert aborted is False
    assert ready == [Point(1000, 800), Point(1070, 800)]
    clicks = [c for c in driver.calls if c[0] == "click"]
    assert clicks == [
        ("click", 68, 500, "RButton"), ("click", 1070, 800, "LButton"),
    ]


def test_check_phase_skips_unfillable() -> None:
    # 补不满的图不进入可瓦列表（不瓦未满 6 词的地图）
    s = _craft_settings()
    rare5 = make_text(affixes=5)
    driver = ScriptedDriver({(1000, 800): [rare5, rare5]})
    ready, aborted = _runner(s)._check_phase(driver, Point(1000, 800))
    assert (ready, aborted) == ([], False)


def test_vaal_phase_blind_clicks() -> None:
    # 瓦尔阶段盲点：每格 瓦尔右键→格左键，不读取
    s = _craft_settings()
    cells = [Point(1000, 800), Point(1070, 800)]
    driver = ScriptedDriver({})
    _runner(s)._vaal_phase(driver, cells)
    assert [c for c in driver.calls if c[0] == "read"] == []
    clicks = [c for c in driver.calls if c[0] == "click"]
    assert clicks == [
        ("click", 425, 240, "RButton"), ("click", 1000, 800, "LButton"),
        ("click", 425, 240, "RButton"), ("click", 1070, 800, "LButton"),
    ]


def test_return_phase_four_buckets() -> None:
    # 分流顺序：T16(Map 仓) → ≥100(100 地图仓强存) → 8 词(高级地图仓强存) → 其他(Map 仓)
    s = _small_stash_settings()
    items = [
        (Point(1000, 800), parse_waystone(make_text(tier=16, affixes=6, corrupted=True))),
        (Point(1070, 800), parse_waystone(make_text(affixes=6, corrupted=True,
                                                    item_rarity=60, monster_effect=45))),
        (Point(1140, 800), parse_waystone(make_text(affixes=8, corrupted=True))),
        (Point(1210, 800), parse_waystone(make_text(affixes=6, corrupted=True))),
    ]
    driver = FakeDriver({})
    _runner(s)._return_phase(driver, items)
    clicks = [c for c in driver.calls if c[0] == "click"]
    assert [c[1:3] for c in clicks] == [
        (s.stash_ui.tab_map.x, s.stash_ui.tab_map.y),
        (s.stash_ui.tab_map100.x, s.stash_ui.tab_map100.y),
        (s.stash_ui.tab_advanced_map.x, s.stash_ui.tab_advanced_map.y),
        (s.stash_ui.tab_map.x, s.stash_ui.tab_map.y),
    ]
    ctrl_clicks = [c for c in driver.calls if c[0] == "ctrl_click"]
    assert [(c[1], c[2]) for c in ctrl_clicks] == [(1000, 800), (1210, 800)]  # T16 先，其他最后
    force_clicks = [c for c in driver.calls if c[0] == "ctrl_shift_click"]
    assert [(c[1], c[2]) for c in force_clicks] == [(1070, 800), (1140, 800)]  # 先 100 仓后高级仓


def test_return_phase_all_normal() -> None:
    s = _small_stash_settings()
    items = [
        (Point(1000, 800), parse_waystone(make_text(affixes=6, corrupted=True))),
        (Point(1070, 800), parse_waystone(make_text(affixes=7, corrupted=True))),
    ]
    driver = FakeDriver({})
    _runner(s)._return_phase(driver, items)
    clicks = [c for c in driver.calls if c[0] == "click"]
    assert len(clicks) == 1  # 只切 Map 页，空桶不切仓
    assert [c for c in driver.calls if c[0] == "ctrl_shift_click"] == []
    assert len([c for c in driver.calls if c[0] == "ctrl_click"]) == 2


# ============================================================
# OpenCV 占用检测（纯逻辑）
# ============================================================
def test_occupied_cells_in_image() -> None:
    import numpy as np

    from poe2_tools.modules.map_vaal import occupied_cells_in_image

    # 2×2 网格，格距 70，首格中心 (35,35)；只有 (行1,列0) 有亮块
    gray = np.full((140, 140), 8, dtype=np.uint8)  # 空格亮度≈8
    gray[105 - 20:105 + 20, 35 - 20:35 + 20] = 80  # 有物品格亮度≈80
    result = occupied_cells_in_image(gray, Point(35, 35), 70, 2, 2)
    assert result == {(1, 0)}


def test_is_unidentified_waystone() -> None:
    from poe2_tools.modules.map_vaal import is_unidentified_waystone

    assert is_unidentified_waystone(make_text(affixes=0) + "\r\n--------\r\n未鑑定")
    assert not is_unidentified_waystone(make_text(affixes=5))
    assert not is_unidentified_waystone(None)
    assert not is_unidentified_waystone("物品種類: 可堆疊通貨\r\n未鑑定")
