#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""模块物品展示顺序测试：与 poe2db 页面返回顺序（sort_order）一致。"""

import sqlite3

import pytest

from web import db


@pytest.fixture()
def tmp_db(tmp_path):
    path = tmp_path / "test.db"
    db.init_db(db_path=path)
    return path


def _seed_module(db_path, slugs_in_page_order):
    """按页面顺序插入物品（slug 故意与页面顺序不一致），返回 (season_id, module_slug)。"""
    module_slug = "Economy_Currency"
    db.upsert_module(module_slug, "通货", db_path=db_path)
    module = db.get_module_by_slug(module_slug, db_path=db_path)
    season_id = db.create_season("S1", "2026-10-01", db_path=db_path)
    for order, slug in enumerate(slugs_in_page_order):
        item_id = db.upsert_item(module["id"], slug, slug, slug, None, None,
                                 sort_order=order, db_path=db_path)
        db.insert_snapshot(item_id, season_id, "2026-10-02T10:00:00",
                           {"ref_amount": 1.0, "ref_currency": "divine",
                            "item_amount": 1.0}, db_path=db_path)
    return season_id, module_slug


def test_snapshots_follow_page_order(tmp_db):
    # 页面顺序：mirror 最前；slug 字母序会把 chaos 排最前
    page_order = ["mirror", "divine", "chaos"]
    season_id, module_slug = _seed_module(tmp_db, page_order)
    _, rows = db.get_module_snapshots(module_slug, season_id, db_path=tmp_db)
    assert [r["slug"] for r in rows] == page_order


def test_upsert_item_updates_sort_order(tmp_db):
    page_order = ["mirror", "divine", "chaos"]
    season_id, module_slug = _seed_module(tmp_db, page_order)
    module = db.get_module_by_slug(module_slug, db_path=tmp_db)
    # 模拟再次抓取，页面顺序变化
    new_order = ["chaos", "mirror", "divine"]
    for order, slug in enumerate(new_order):
        db.upsert_item(module["id"], slug, slug, slug, None, None,
                       sort_order=order, db_path=tmp_db)
    _, rows = db.get_module_snapshots(module_slug, season_id, db_path=tmp_db)
    assert [r["slug"] for r in rows] == new_order


def test_upsert_item_none_keeps_sort_order(tmp_db):
    page_order = ["mirror", "divine", "chaos"]
    season_id, module_slug = _seed_module(tmp_db, page_order)
    module = db.get_module_by_slug(module_slug, db_path=tmp_db)
    # 不传 sort_order 更新其他字段时，原有顺序保留
    db.upsert_item(module["id"], "divine", "神圣石", "Divine Orb", None, None,
                   db_path=tmp_db)
    _, rows = db.get_module_snapshots(module_slug, season_id, db_path=tmp_db)
    assert [r["slug"] for r in rows] == page_order


def test_library_items_follow_page_order(tmp_db):
    page_order = ["mirror", "divine", "chaos"]
    _seed_module(tmp_db, page_order)
    rows = db.list_library_items(module_slug="Economy_Currency", db_path=tmp_db)
    assert [r["slug"] for r in rows] == page_order


def test_init_db_migrates_old_items_table(tmp_path):
    """旧库 items 表无 sort_order 列时，init_db 自动补列。"""
    path = tmp_path / "old.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """CREATE TABLE items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            module_id INTEGER NOT NULL,
            slug TEXT NOT NULL,
            name_zh TEXT NOT NULL,
            name_en TEXT,
            icon_path TEXT,
            wiki_slug TEXT,
            UNIQUE(module_id, slug)
        )""")
    conn.commit()
    conn.close()
    db.init_db(db_path=path)
    with sqlite3.connect(path) as conn:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(items)")]
    assert "sort_order" in cols
