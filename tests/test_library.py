# -*- coding: utf-8 -*-
"""信息库：wiki 页面解析、item_info 存储与检索、抓取编排的单元测试。"""

from pathlib import Path

import pytest

from web import db, scraper, service

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load(name):
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


@pytest.fixture()
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(db_path=path)
    return path


def _seed_library(db_path):
    """造两个模块三个物品（均带 wiki 链接），返回 {slug: item_id}。"""
    db.upsert_module("Economy_Currency", "通貨", db_path=db_path)
    db.upsert_module("Economy_Essences", "精髓", db_path=db_path)
    m1 = db.get_module_by_slug("Economy_Currency", db_path=db_path)
    m2 = db.get_module_by_slug("Economy_Essences", db_path=db_path)
    return {
        "divine": db.upsert_item(m1["id"], "divine", "神聖石", "Divine Orb",
                                 None, "Divine_Orb", db_path=db_path),
        "chaos": db.upsert_item(m1["id"], "chaos", "混沌石", "Chaos Orb",
                                None, "Chaos_Orb", db_path=db_path),
        "haste": db.upsert_item(m2["id"], "haste", "迅捷精髓",
                                "Essence of Haste", None, "Essence_of_Haste",
                                db_path=db_path),
    }


# ---------- wiki 页面解析 ----------

def test_parse_wiki_gold_and_names():
    info = scraper.parse_wiki_item_info(_load("wiki_divine_orb.html"))
    assert info["gold_cost"] == 800.0
    assert info["name_zh"] == "神聖石"
    assert info["name_en"] == "Divine Orb"


def test_parse_wiki_without_currency_exchange():
    info = scraper.parse_wiki_item_info(_load("wiki_uncut_gem.html"))
    assert info["gold_cost"] is None
    assert info["name_zh"] == "未切割的技能寶石"
    assert info["name_en"] == "Uncut Skill Gem"


def test_parse_wiki_empty_html():
    info = scraper.parse_wiki_item_info("<html><body></body></html>")
    assert info == {"gold_cost": None, "name_zh": None, "name_en": None}


# ---------- item_info 存储与检索 ----------

def test_upsert_and_list_library(tmp_db):
    ids = _seed_library(tmp_db)
    db.upsert_item_info(ids["divine"], "https://poe2db.tw/tw/Divine_Orb",
                        800.0, "神聖石", "Divine Orb", db_path=tmp_db)
    rows = db.list_library_items(db_path=tmp_db)
    assert len(rows) == 3
    divine = next(r for r in rows if r["slug"] == "divine")
    assert divine["gold_cost"] == 800.0
    assert divine["wiki_url"] == "https://poe2db.tw/tw/Divine_Orb"
    assert divine["module_slug"] == "Economy_Currency"
    assert divine["module_name_zh"] == "通貨"
    assert divine["info_fetched_at"]
    # 未抓过 wiki 的物品：金币与抓取时间为 None，名称回落到 items 表
    chaos = next(r for r in rows if r["slug"] == "chaos")
    assert chaos["gold_cost"] is None
    assert chaos["info_fetched_at"] is None
    assert chaos["name_zh"] == "混沌石"


def test_upsert_item_info_overwrites(tmp_db):
    ids = _seed_library(tmp_db)
    db.upsert_item_info(ids["divine"], "u1", 800.0, "神聖石", "Divine Orb", db_path=tmp_db)
    db.upsert_item_info(ids["divine"], "u2", 900.0, "神聖石", "Divine Orb", db_path=tmp_db)
    rows = [r for r in db.list_library_items(db_path=tmp_db) if r["slug"] == "divine"]
    assert len(rows) == 1
    assert rows[0]["gold_cost"] == 900.0
    assert rows[0]["wiki_url"] == "u2"


def test_library_search_bilingual(tmp_db):
    ids = _seed_library(tmp_db)
    db.upsert_item_info(ids["haste"], None, 50.0, "迅捷精髓", "Essence of Haste",
                        db_path=tmp_db)
    # 中文物品名
    assert {r["slug"] for r in db.list_library_items(search="神聖", db_path=tmp_db)} == {"divine"}
    # 英文物品名（大小写不敏感）
    assert {r["slug"] for r in db.list_library_items(search="divine orb", db_path=tmp_db)} == {"divine"}
    # 模块中文名
    assert {r["slug"] for r in db.list_library_items(search="精髓", db_path=tmp_db)} == {"haste"}
    # 模块 slug
    assert len(db.list_library_items(search="Economy_Currency", db_path=tmp_db)) == 2
    # wiki_slug
    assert {r["slug"] for r in db.list_library_items(search="Essence_of", db_path=tmp_db)} == {"haste"}


def test_library_module_filter(tmp_db):
    _seed_library(tmp_db)
    rows = db.list_library_items(module_slug="Economy_Essences", db_path=tmp_db)
    assert {r["slug"] for r in rows} == {"haste"}


def test_wiki_scrape_targets(tmp_db):
    ids = _seed_library(tmp_db)
    # 初始：3 个物品都有 wiki 链接且未抓过
    assert len(db.list_wiki_scrape_targets(only_missing=True, db_path=tmp_db)) == 3
    assert len(db.list_wiki_scrape_targets(only_missing=False, db_path=tmp_db)) == 3
    db.upsert_item_info(ids["divine"], None, None, None, None, db_path=tmp_db)
    # 抓过（即使金币为 None）后不再出现在 missing 清单
    targets = db.list_wiki_scrape_targets(only_missing=True, db_path=tmp_db)
    assert {t["wiki_slug"] for t in targets} == {"Chaos_Orb", "Essence_of_Haste"}


# ---------- 抓取编排 ----------

def test_run_library_scrape(tmp_db, monkeypatch):
    ids = _seed_library(tmp_db)
    monkeypatch.setattr(scraper, "REQUEST_INTERVAL", 0)

    def fake_fetch(wiki_slug, session=None):
        gold = {"Divine_Orb": 800.0, "Chaos_Orb": 100.0,
                "Essence_of_Haste": 50.0}[wiki_slug]
        return {"gold_cost": gold, "name_zh": None, "name_en": None,
                "wiki_url": "https://poe2db.tw/tw/" + wiki_slug}

    monkeypatch.setattr(scraper, "fetch_wiki_item_info", fake_fetch)
    # 未实现 session 时也不应发真实请求
    monkeypatch.setattr(scraper, "_make_session", lambda: None)

    service._run_library_scrape("missing", db_path=tmp_db)

    status = service.get_library_status()
    assert status["running"] is False
    assert status["error"] is None
    assert status["done"] == 3
    assert status["updated"] == 3

    rows = {r["slug"]: r for r in db.list_library_items(db_path=tmp_db)}
    assert rows["divine"]["gold_cost"] == 800.0
    assert rows["chaos"]["gold_cost"] == 100.0
    # 单个物品抓取异常不中断整体，且不计入 updated
    def fail_fetch(wiki_slug, session=None):
        raise RuntimeError("network down")

    monkeypatch.setattr(scraper, "fetch_wiki_item_info", fail_fetch)
    service._run_library_scrape("all", db_path=tmp_db)
    status = service.get_library_status()
    assert status["error"] is None
    assert status["updated"] == 0
    # 旧数据保留
    rows = {r["slug"]: r for r in db.list_library_items(db_path=tmp_db)}
    assert rows["divine"]["gold_cost"] == 800.0
