# -*- coding: utf-8 -*-
"""web/scraper.py 解析器单元测试：使用 tests/fixtures/ 下的真实页面快照。"""

from pathlib import Path

import pytest

from web import scraper

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name):
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def currency_items():
    return scraper.parse_module_page(_load("eco_currency.html"))["items"]


@pytest.fixture(scope="module")
def gems_items():
    return scraper.parse_module_page(_load("eco_gems.html"))["items"]


@pytest.fixture(scope="module")
def fragments_items():
    return scraper.parse_module_page(_load("eco_fragments.html"))["items"]


# ---------- 行数 ----------

def test_currency_row_count(currency_items):
    assert len(currency_items) == 13


def test_gems_row_count(gems_items):
    assert len(gems_items) == 13


def test_fragments_row_count(fragments_items):
    assert len(fragments_items) == 8


# ---------- 名称 / slug / 英文名 ----------

def test_name_slug_en_parsing(currency_items):
    divine = next(i for i in currency_items if i["wiki_slug"] == "Divine_Orb")
    assert divine["slug"] == "divine"
    assert divine["name_zh"] == "神聖石"
    assert divine["name_en"] == "Divine Orb"
    assert divine["icon_url"].startswith("https://web.poecdn.com/")


def test_all_rows_have_name_and_slug(currency_items, gems_items, fragments_items):
    for item in currency_items + gems_items + fragments_items:
        assert item["slug"]
        assert item["name_zh"]
        assert item["wiki_slug"]


# ---------- 价格解析 ----------

def test_price_divine_ref(gems_items):
    # 参照货币为 divine：30 divine ⇄ 1 物品
    item = next(i for i in gems_items if i["slug"] == "ataluis-bloodletting")
    assert item["ref_currency"] == "divine"
    assert item["ref_amount"] == 30.0
    assert item["item_amount"] == 1.0


def test_price_chaos_ref(currency_items):
    # 神聖石行：17.6 chaos ⇄ 1 divine
    divine = next(i for i in currency_items if i["wiki_slug"] == "Divine_Orb")
    assert divine["ref_currency"] == "chaos"
    assert divine["ref_amount"] == pytest.approx(17.6)
    assert divine["item_amount"] == 1.0


def test_price_fractional_item_amount(currency_items):
    # 完美增幅石：1 divine ⇄ 40 物品 → 单价 0.025
    item = next(i for i in currency_items if i["slug"] == "perfect-orb-of-augmentation")
    assert item["ref_currency"] == "divine"
    assert item["ref_amount"] == 1.0
    assert item["item_amount"] == 40.0


# ---------- 涨跌幅与颜色 ----------

def test_change_pct_and_color(currency_items):
    divine = next(i for i in currency_items if i["wiki_slug"] == "Divine_Orb")
    assert divine["change_7d_pct"] == pytest.approx(-13.0)
    assert divine["change_color"] == "red"
    aug = next(i for i in currency_items if i["slug"] == "perfect-orb-of-augmentation")
    assert aug["change_7d_pct"] == pytest.approx(150.0)
    assert aug["change_color"] == "green"


def test_sparkline_d(currency_items):
    divine = next(i for i in currency_items if i["wiki_slug"] == "Divine_Orb")
    assert divine["sparkline_d"].startswith("M 0 ")
    assert " L 60 " in divine["sparkline_d"]


# ---------- 交易量 ----------

def test_volume(currency_items):
    divine = next(i for i in currency_items if i["wiki_slug"] == "Divine_Orb")
    assert divine["volume_24h"] == 192
    for item in currency_items:
        assert item["volume_24h"] is None or isinstance(item["volume_24h"], int)


# ---------- 汇率提取 ----------

def test_extract_chaos_per_divine(currency_items):
    assert scraper.extract_chaos_per_divine(currency_items) == pytest.approx(17.6)


def test_extract_chaos_per_divine_missing(gems_items):
    # 非 Currency 模块没有神聖石行，应返回 None
    assert scraper.extract_chaos_per_divine(gems_items) is None


# ---------- price_divine / price_chaos 换算 ----------

def test_compute_prices_divine_ref():
    price_divine, price_chaos = scraper.compute_prices("divine", 2.0, 1.0, 17.6)
    assert price_divine == pytest.approx(2.0)
    assert price_chaos == pytest.approx(35.2)


def test_compute_prices_chaos_ref():
    price_divine, price_chaos = scraper.compute_prices("chaos", 17.6, 1.0, 17.6)
    assert price_divine == pytest.approx(1.0)
    assert price_chaos == pytest.approx(17.6)


def test_compute_prices_fractional():
    # 1 divine ⇄ 40 物品 → 单价 0.025 神圣
    price_divine, price_chaos = scraper.compute_prices("divine", 1.0, 40.0, 17.6)
    assert price_divine == pytest.approx(0.025)
    assert price_chaos == pytest.approx(0.44)


def test_compute_prices_other_ref():
    # 其他参照货币（如 exalted）→ NULL
    price_divine, price_chaos = scraper.compute_prices("exalted", 5.0, 1.0, 17.6)
    assert price_divine is None
    assert price_chaos is None


def test_compute_prices_no_rate():
    # 未知汇率时 chaos 参照无法换算成 divine
    price_divine, price_chaos = scraper.compute_prices("chaos", 10.0, 1.0, None)
    assert price_divine is None
    assert price_chaos == pytest.approx(10.0)


# ---------- 模块卡片 ----------

def test_module_cards():
    parsed = scraper.parse_module_page(_load("eco_currency.html"))
    cards = {c["slug"]: c for c in parsed["modules"]}
    assert len(cards) == 14
    assert cards["Economy_Currency"]["name_zh"] == "通貨"
    assert cards["Economy_Atziris_Temple"]["name_zh"] == "阿茲里的神廟"
    assert cards["Economy_Fragments"]["icon_url"].endswith(".webp")
