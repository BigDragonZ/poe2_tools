#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通货市场抓取单元测试：OCR 文本解析、坐标校验与抓取流程（注入假驱动/OCR）。"""

from __future__ import annotations

import pytest

from poe2_tools.config.settings import (
    Point,
    Settings,
    load_settings,
    save_settings,
)
from poe2_tools.modules.market import scanner as scanner_mod
from poe2_tools.modules.market.parser import (
    TextBlock,
    has_stock_feature,
    parse_market_blocks,
    parse_market_lines,
)
from poe2_tools.modules.market.scanner import (
    POINT_SLOTS,
    RESULT_RANGE_SLOT,
    CurrencyTradeScanner,
    UnsetCoordinateError,
)


# ============================================================
# OCR 文本解析（纯逻辑）
# ============================================================
def test_has_stock_feature_chinese() -> None:
    assert has_stock_feature("库存 42")
    assert has_stock_feature("库 存：120")  # OCR 字间空格


def test_has_stock_feature_english_fuzzy() -> None:
    assert has_stock_feature("Stock 120")
    assert has_stock_feature("stock: 8")
    assert has_stock_feature("5tock 3")   # S → 5 混淆
    assert has_stock_feature("St0ck 99")  # o → 0 混淆


def test_has_stock_feature_negative() -> None:
    assert not has_stock_feature("Divine Orb 1:155")
    assert not has_stock_feature("")


def test_parse_ratio_colon_and_slash() -> None:
    """冒号/斜杠比例都解析，输出统一为冒号分隔。"""
    lines = ["1:155 库存 42", "1/160 Stock 7"]
    result = parse_market_lines(lines)
    assert [r["ratio"] for r in result] == ["1:155", "1:160"]
    assert [r["stock"] for r in result] == [42, 7]


def test_parse_stock_thousands_and_rank() -> None:
    """库存支持千分位逗号；rank 按顺序从 1 起。"""
    lines = ["1:2 库存 1,250", "垃圾行没有特征", "158:1 Stock 450"]
    result = parse_market_lines(lines)
    assert result == [
        {"rank": 1, "ratio": "1:2", "stock": 1250},
        {"rank": 2, "ratio": "158:1", "stock": 450},
    ]


def test_parse_stock_before_ratio() -> None:
    """库存特征在比例之前时，取特征词后的第一个整数。"""
    result = parse_market_lines(["库存 120 → 1:155"])
    assert result == [{"rank": 1, "ratio": "1:155", "stock": 120}]


def test_parse_no_ratio_returns_empty() -> None:
    """全部行都解析不出比例 → 空数组（该方向无可用交易）。"""
    assert parse_market_lines(["Divine Orb", "Chaos Orb", ""]) == []


def test_parse_ratio_without_stock_feature() -> None:
    """识别到比率但识别不到库存特征 → 仍返回比率，stock 为 None。"""
    result = parse_market_lines(["1:155 Divine Orb", "2:30 Chaos"])
    assert result == [
        {"rank": 1, "ratio": "1:155", "stock": None},
        {"rank": 2, "ratio": "2:30", "stock": None},
    ]


def test_parse_stock_on_separate_line_merged() -> None:
    """OCR 把比例与库存拆成两行（不同列）→ 库存合并到相邻挂单。"""
    result = parse_market_lines(["1:155", "库存 120", "1:160", "Stock 7"])
    assert result == [
        {"rank": 1, "ratio": "1:155", "stock": 120},
        {"rank": 2, "ratio": "1:160", "stock": 7},
    ]


def test_parse_stock_line_before_ratio_stashed() -> None:
    """库存行出现在比例行之前（表头串行）→ 暂存给下一条挂单。"""
    result = parse_market_lines(["库存 88", "2:30"])
    assert result == [{"rank": 1, "ratio": "2:30", "stock": 88}]


def test_parse_orphan_stock_line_ignored() -> None:
    """只有库存行、全屏无比例 → 空数组。"""
    assert parse_market_lines(["库存 120", "Stock 7"]) == []


# ============================================================
# 带坐标文本块解析（行聚合 + 行内配对）
# ============================================================
def _block(text: str, cx: float, cy: float, h: float = 12.0) -> TextBlock:
    return TextBlock(text=text, cx=cx, cy=cy, h=h)


def test_blocks_real_layout_stock_left() -> None:
    """实测 a→b 布局：库存列在左、比例列在右，裸数字库存配对到同行比例；只取前三条。"""
    blocks = [
        _block("市場比率", 10, 10), _block("10.40:1", 150, 10),
        _block("比率", 150, 30), _block("库存", 50, 30),
        _block("624", 50, 50), _block("10.40: 1", 150, 50),
        _block("551", 50, 70), _block("10.40:1", 150, 70),
        _block("10.40: 1", 150, 90), _block("3,359", 50, 90),
        _block("10.40:1", 150, 110), _block("2,339", 50, 110),
        _block("033", 50, 130), _block("1033", 150, 130),
    ]
    assert parse_market_blocks(blocks) == [
        {"rank": 1, "ratio": "10.40:1", "stock": None},
        {"rank": 2, "ratio": "10.40:1", "stock": 624},
        {"rank": 3, "ratio": "10.40:1", "stock": 551},
    ]


def test_blocks_multi_pairs_one_row() -> None:
    """实测 b→a 布局：一行内两组 比例+库存（比例列在左）。"""
    blocks = [
        _block("市場比率", 10, 10), _block("1:10.40", 100, 10), _block("52", 180, 10),
        _block("1:10.40", 250, 10), _block("4,000", 330, 10), _block("下訂單", 420, 10),
    ]
    assert parse_market_blocks(blocks) == [
        {"rank": 1, "ratio": "1:10.40", "stock": 52},
        {"rank": 2, "ratio": "1:10.40", "stock": 4000},
    ]


def test_blocks_stock_thousand_dot_and_decimal() -> None:
    """库存含千分位点（875.556 → 875556）与小数（10.40 → 10.4）都能识别。"""
    blocks = [
        _block("875.556", 50, 10), _block("1:10.40", 150, 10),
        _block("10.40", 50, 30), _block("2:30", 150, 30),
    ]
    assert parse_market_blocks(blocks) == [
        {"rank": 1, "ratio": "1:10.40", "stock": 875556},
        {"rank": 2, "ratio": "2:30", "stock": 10.4},
    ]


def test_parse_line_without_ratio_skipped() -> None:
    """有库存特征但无比例 → 跳过该行。"""
    assert parse_market_lines(["库存若干"]) == []


# ============================================================
# 抓取流程（假驱动 + 假 OCR）
# ============================================================
class FakeDriver:
    """记录调用序列的假驱动。"""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def sleep_ms(self, ms: int) -> None:
        self.calls.append(("sleep", ms))

    def click_position(self, point: Point, modifier: str | None = None) -> None:
        self.calls.append(("click", point.x, point.y, modifier))

    def input_from_clipboard(self, point: Point) -> None:
        self.calls.append(("paste", point.x, point.y))

    def capture_region(self, rect: tuple[int, int, int, int]) -> str:
        self.calls.append(("capture", rect))
        return f"image@{len(self.calls)}"  # 用字符串充当图像


class FakeOcr:
    """按图像标识返回预设文本块（每行一块、各自成行）的假 OCR。"""

    def __init__(self, mapping: dict[str, list[str]]) -> None:
        self._mapping = mapping
        self.seen: list[str] = []

    def recognize_blocks(self, image) -> list[TextBlock]:
        self.seen.append(image)
        return [
            TextBlock(text=t, cx=0.0, cy=float(i * 20), h=12.0)
            for i, t in enumerate(self._mapping.get(image, []))
        ]


def _calibrated_settings() -> Settings:
    s = Settings()
    for slot in POINT_SLOTS.values():
        s.dev.measure_points[slot] = Point(slot * 10, slot * 100)
    s.dev.measure_ranges[RESULT_RANGE_SLOT] = (50, 60, 500, 600)
    return s


def _make_scanner(monkeypatch: pytest.MonkeyPatch, settings: Settings,
                  ocr: FakeOcr, driver: FakeDriver) -> tuple[CurrencyTradeScanner, list[str]]:
    """构造扫描器并把剪贴板写入替换为记录列表。"""
    clipboard: list[str] = []
    monkeypatch.setattr(scanner_mod, "copy_to_clipboard", clipboard.append)
    return CurrencyTradeScanner(settings, driver=driver, ocr=ocr), clipboard


def test_scan_full_workflow(monkeypatch: pytest.MonkeyPatch) -> None:
    """完整流程：两阶段点击序列、Ctrl 反转、双向结果与数据契约。"""
    settings = _calibrated_settings()
    driver = FakeDriver()
    # FakeDriver 的 capture 返回 "image@N"：第一次截图 N=…，用 seen 顺序对 OCR 映射
    ocr = FakeOcr({})
    scan, clipboard = _make_scanner(monkeypatch, settings, ocr, driver)

    # 预先按调用顺序准备 OCR 结果：先 b_to_a，后 a_to_b
    results = iter([
        ["1:155 库存 120"],
        ["158:1 Stock 450", "1:1 无特征行"],
    ])

    def fake_blocks(image) -> list[TextBlock]:
        return [
            TextBlock(text=t, cx=0.0, cy=float(i * 20), h=12.0)
            for i, t in enumerate(next(results))
        ]

    ocr.recognize_blocks = fake_blocks  # type: ignore[method-assign]

    out = scan.scan("Divine Orb", "Chaos Orb")

    # 数据契约
    assert out["success"] is True
    assert out["pair"] == "Divine Orb <-> Chaos Orb"
    assert out["b_to_a"] == [{"rank": 1, "ratio": "1:155", "stock": 120}]
    assert out["a_to_b"] == [
        {"rank": 1, "ratio": "158:1", "stock": 450},
        {"rank": 2, "ratio": "1:1", "stock": None},  # 无库存特征仍返回比率
    ]

    # 剪贴板顺序：先 WANT(A) 后 HAVE(B)
    assert clipboard == ["Divine Orb", "Chaos Orb"]

    # 关键调用序列：Phase1 搜索×2 → 比率键 → 截屏；Phase2 Ctrl 反转 → 比率键 → 截屏
    clicks = [c for c in driver.calls if c[0] == "click"]
    captures = [c for c in driver.calls if c[0] == "capture"]
    pastes = [c for c in driver.calls if c[0] == "paste"]
    assert len(pastes) == 2 and len(captures) == 2
    # Ctrl 修饰点击只出现一次，目标是「我需要的」(point1 = (10, 100))
    ctrl_clicks = [c for c in clicks if c[3] == "Ctrl"]
    assert ctrl_clicks == [("click", 10, 100, "Ctrl")]
    # 截屏范围是 range3 加默认偏移（左移 10、下移 20）
    assert captures[0][1] == (40, 80, 490, 620)


def test_scan_retries_when_first_capture_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """首次解析为空时自动重试一次：再点市场比率键后再截屏解析。"""
    settings = _calibrated_settings()
    driver = FakeDriver()
    ocr = FakeOcr({})
    scan, _ = _make_scanner(monkeypatch, settings, ocr, driver)

    # b_to_a：首次空、重试有数据；a_to_b：首次即有数据（不重试）
    results = iter([
        [],
        [TextBlock(text="1:155", cx=150.0, cy=10.0, h=12.0),
         TextBlock(text="875.556", cx=50.0, cy=10.0, h=12.0)],
        [TextBlock(text="158:1 库存 450", cx=100.0, cy=10.0, h=12.0)],
    ])
    ocr.recognize_blocks = lambda image: next(results)  # type: ignore[method-assign]

    out = scan.scan("Divine Orb", "Chaos Orb")
    assert out["b_to_a"] == [{"rank": 1, "ratio": "1:155", "stock": 875556}]
    assert out["a_to_b"] == [{"rank": 1, "ratio": "158:1", "stock": 450}]
    # 市场比率按键（point4 = (40, 400)）：Phase1 点了 2 次（首次 + 重试），Phase2 点 1 次
    rate_clicks = [c for c in driver.calls if c == ("click", 40, 400, None)]
    assert len(rate_clicks) == 3


def test_scan_no_offers_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """OCR 未识别到库存 → 双向均为标准空数据（重试后仍为空）。"""
    settings = _calibrated_settings()
    ocr = FakeOcr({})  # 任何图像都返回空行列表
    scan, _ = _make_scanner(monkeypatch, settings, ocr, FakeDriver())

    out = scan.scan("Divine Orb", "Chaos Orb")
    assert out == {
        "success": True,
        "pair": "Divine Orb <-> Chaos Orb",
        "b_to_a": [],
        "a_to_b": [],
    }


def test_scan_unset_coordinate_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """缺任一坐标点或范围 → UnsetCoordinateError，且不产生任何点击。"""
    settings = Settings()  # 全部未标定
    scan, _ = _make_scanner(monkeypatch, settings, FakeOcr({}), FakeDriver())
    with pytest.raises(UnsetCoordinateError):
        scan.scan("Divine Orb", "Chaos Orb")

    settings2 = _calibrated_settings()
    del settings2.dev.measure_ranges[RESULT_RANGE_SLOT]
    driver2 = FakeDriver()
    scan2, _ = _make_scanner(monkeypatch, settings2, FakeOcr({}), driver2)
    with pytest.raises(UnsetCoordinateError):
        scan2.scan("Divine Orb", "Chaos Orb")
    assert driver2.calls == []  # 校验失败时不执行任何动作


# ============================================================
# [MarketScan] 配置读写回环
# ============================================================
def test_market_scan_settings_roundtrip(tmp_path) -> None:
    ini = tmp_path / "t.ini"
    s = Settings()
    s.market_scan.click_delay_ms = 200
    s.market_scan.search_load_delay_ms = 450
    s.market_scan.ui_refresh_delay_ms = 600
    s.market_scan.select_delay_ms = 700
    s.market_scan.hotkey = "f9"
    s.market_scan.hotkey_default = "f6"
    s.market_scan.hotkey_custom = "f7"
    s.market_scan.custom_currency = "Orb of Annulment"
    s.market_scan.range_offset_x = -25
    s.market_scan.range_offset_y = 35
    s.market_scan.currency_a = "Exalted Orb"
    s.market_scan.currency_b = "Vaal Orb"
    save_settings(s, ini)

    loaded = load_settings(ini)
    assert loaded.market_scan.click_delay_ms == 200
    assert loaded.market_scan.search_load_delay_ms == 450
    assert loaded.market_scan.ui_refresh_delay_ms == 600
    assert loaded.market_scan.select_delay_ms == 700
    assert loaded.market_scan.hotkey == "f9"
    assert loaded.market_scan.hotkey_default == "f6"
    assert loaded.market_scan.hotkey_custom == "f7"
    assert loaded.market_scan.custom_currency == "Orb of Annulment"
    assert loaded.market_scan.range_offset_x == -25
    assert loaded.market_scan.range_offset_y == 35
    assert loaded.market_scan.currency_a == "Exalted Orb"
    assert loaded.market_scan.currency_b == "Vaal Orb"


def test_market_scan_settings_defaults(tmp_path) -> None:
    loaded = load_settings(tmp_path / "missing.ini")
    assert loaded.market_scan.click_delay_ms == 300
    assert loaded.market_scan.search_load_delay_ms == 1200
    assert loaded.market_scan.ui_refresh_delay_ms == 800
    assert loaded.market_scan.select_delay_ms == 500
    assert loaded.market_scan.hotkey == "f8"
    assert loaded.market_scan.hotkey_default == "f9"
    assert loaded.market_scan.hotkey_custom == "f10"
    assert loaded.market_scan.custom_currency == ""
    assert loaded.market_scan.range_offset_x == -10
    assert loaded.market_scan.range_offset_y == 20
    assert loaded.market_scan.currency_a == "Divine Orb"
    assert loaded.market_scan.currency_b == "Chaos Orb"
