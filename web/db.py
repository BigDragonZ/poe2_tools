"""SQLite 存储层：schema 定义与读写函数。

数据库文件默认位于 web/data/economy.db。
所有写操作通过全局锁串行化，每次操作开短连接，避免多线程冲突。
"""

import sqlite3
import threading
from datetime import date, datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "economy.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS seasons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    start_date TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    slug TEXT UNIQUE NOT NULL,
    name_zh TEXT NOT NULL,
    icon_path TEXT
);
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    module_id INTEGER NOT NULL REFERENCES modules(id),
    slug TEXT NOT NULL,
    name_zh TEXT NOT NULL,
    name_en TEXT,
    icon_path TEXT,
    wiki_slug TEXT,
    UNIQUE(module_id, slug)
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER NOT NULL REFERENCES items(id),
    season_id INTEGER NOT NULL REFERENCES seasons(id),
    fetched_at TEXT NOT NULL,
    ref_amount REAL,
    ref_currency TEXT,
    item_amount REAL,
    price_divine REAL,
    price_chaos REAL,
    change_7d_pct REAL,
    change_color TEXT,
    sparkline_d TEXT,
    volume_24h INTEGER
);
CREATE INDEX IF NOT EXISTS idx_snapshots_item_season ON snapshots(item_id, season_id, fetched_at);
CREATE TABLE IF NOT EXISTS fetch_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    season_id INTEGER REFERENCES seasons(id),
    module_slug TEXT,
    fetched_at TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT
);
CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

# 写操作全局锁，保证 SQLite 写串行化
_DB_LOCK = threading.Lock()


def _connect(db_path=None):
    """开一个新的短连接。"""
    path = str(db_path or DB_PATH)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    """建表（幂等）。"""
    with _DB_LOCK, _connect(db_path) as conn:
        conn.executescript(_SCHEMA)


def _now():
    return datetime.now().isoformat(timespec="seconds")


# ---------- 赛季 ----------

def create_season(name, start_date, db_path=None):
    """新增赛季，start_date 格式 YYYY-MM-DD，返回赛季 id。"""
    with _DB_LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO seasons(name, start_date, created_at) VALUES (?, ?, ?)",
            (name, start_date, _now()),
        )
        return cur.lastrowid


def update_season(season_id, name, start_date, db_path=None):
    with _DB_LOCK, _connect(db_path) as conn:
        conn.execute(
            "UPDATE seasons SET name = ?, start_date = ? WHERE id = ?",
            (name, start_date, season_id),
        )


def list_seasons(db_path=None):
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM seasons ORDER BY start_date DESC, id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def get_season(season_id, db_path=None):
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM seasons WHERE id = ?", (season_id,)).fetchone()
        return dict(row) if row else None


def get_current_season(db_path=None):
    """当前赛季 = start_date 最新者。"""
    with _connect(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM seasons ORDER BY start_date DESC, id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None


# ---------- 模块 ----------

def upsert_module(slug, name_zh, icon_path=None, db_path=None):
    with _DB_LOCK, _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO modules(slug, name_zh, icon_path) VALUES (?, ?, ?)
               ON CONFLICT(slug) DO UPDATE SET name_zh = excluded.name_zh,
               icon_path = COALESCE(excluded.icon_path, modules.icon_path)""",
            (slug, name_zh, icon_path),
        )


def list_modules(db_path=None):
    with _connect(db_path) as conn:
        rows = conn.execute("SELECT * FROM modules ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def get_module_by_slug(slug, db_path=None):
    with _connect(db_path) as conn:
        row = conn.execute("SELECT * FROM modules WHERE slug = ?", (slug,)).fetchone()
        return dict(row) if row else None


# ---------- 物品与快照 ----------

def upsert_item(module_id, slug, name_zh, name_en, icon_path, wiki_slug, db_path=None):
    """按 (module_id, slug) 幂等插入/更新物品，返回物品 id。"""
    with _DB_LOCK, _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO items(module_id, slug, name_zh, name_en, icon_path, wiki_slug)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(module_id, slug) DO UPDATE SET
                   name_zh = excluded.name_zh,
                   name_en = excluded.name_en,
                   wiki_slug = excluded.wiki_slug,
                   icon_path = COALESCE(excluded.icon_path, items.icon_path)""",
            (module_id, slug, name_zh, name_en, icon_path, wiki_slug),
        )
        row = conn.execute(
            "SELECT id FROM items WHERE module_id = ? AND slug = ?",
            (module_id, slug),
        ).fetchone()
        return row["id"]


def insert_snapshot(item_id, season_id, fetched_at, snap, db_path=None):
    """插入一条价格快照，snap 为解析出的价格/走势/交易量字段 dict。"""
    with _DB_LOCK, _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO snapshots(item_id, season_id, fetched_at, ref_amount,
                   ref_currency, item_amount, price_divine, price_chaos,
                   change_7d_pct, change_color, sparkline_d, volume_24h)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                item_id, season_id, fetched_at,
                snap.get("ref_amount"), snap.get("ref_currency"),
                snap.get("item_amount"), snap.get("price_divine"),
                snap.get("price_chaos"), snap.get("change_7d_pct"),
                snap.get("change_color"), snap.get("sparkline_d"),
                snap.get("volume_24h"),
            ),
        )


def get_module_snapshots(module_slug, season_id, target_date=None, db_path=None):
    """取某模块某赛季指定日期（默认有数据的最新日期）每物品的最新一条快照。

    返回 (fetched_at 或 None, [行 dict 列表])。
    """
    with _connect(db_path) as conn:
        if target_date is None:
            row = conn.execute(
                """SELECT MAX(date(s.fetched_at)) AS d FROM snapshots s
                   JOIN items i ON i.id = s.item_id
                   JOIN modules m ON m.id = i.module_id
                   WHERE m.slug = ? AND s.season_id = ?""",
                (module_slug, season_id),
            ).fetchone()
            target_date = row["d"] if row else None
        if target_date is None:
            return None, []
        rows = conn.execute(
            """SELECT i.slug, i.name_zh, i.name_en, i.icon_path, i.wiki_slug,
                      s.fetched_at, s.ref_amount, s.ref_currency, s.item_amount,
                      s.price_divine, s.price_chaos, s.change_7d_pct,
                      s.change_color, s.sparkline_d, s.volume_24h
               FROM snapshots s
               JOIN items i ON i.id = s.item_id
               JOIN modules m ON m.id = i.module_id
               WHERE m.slug = ? AND s.season_id = ? AND date(s.fetched_at) = ?
                 AND s.fetched_at = (
                     SELECT MAX(s2.fetched_at) FROM snapshots s2
                     WHERE s2.item_id = s.item_id AND s2.season_id = s.season_id
                       AND date(s2.fetched_at) = ?)
               ORDER BY i.slug""",
            (module_slug, season_id, target_date, target_date),
        ).fetchall()
        return target_date, [dict(r) for r in rows]


def get_item_icons_by_slugs(slugs, db_path=None):
    """按物品 slug 查本地图标路径（用于价格列参照货币图标），返回 {slug: icon_path}。"""
    if not slugs:
        return {}
    placeholders = ",".join("?" for _ in slugs)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT slug, icon_path FROM items WHERE slug IN ({placeholders}) "
            "AND icon_path IS NOT NULL GROUP BY slug",
            list(slugs),
        ).fetchall()
        return {r["slug"]: r["icon_path"] for r in rows}


def list_snapshot_days(module_slug, season_id, season_start_date, db_path=None):
    """返回该模块有数据的开服天数列表（升序）。开服天数 = 快照日期 - 开服日期 + 1。"""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT DISTINCT date(s.fetched_at) AS d FROM snapshots s
               JOIN items i ON i.id = s.item_id
               JOIN modules m ON m.id = i.module_id
               WHERE m.slug = ? AND s.season_id = ? ORDER BY d""",
            (module_slug, season_id),
        ).fetchall()
    start = date.fromisoformat(season_start_date)
    days = []
    for r in rows:
        days.append((date.fromisoformat(r["d"]) - start).days + 1)
    return days


# ---------- 抓取记录 ----------

def insert_fetch_run(season_id, module_slug, status, message=None, db_path=None):
    """记录一次抓取。module_slug 为 None 表示全量刷新。"""
    with _DB_LOCK, _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO fetch_runs(season_id, module_slug, fetched_at, status, message) VALUES (?, ?, ?, ?, ?)",
            (season_id, module_slug, _now(), status, message),
        )


def list_recent_fetch_runs(limit=20, db_path=None):
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM fetch_runs ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def latest_fetch_time_by_module(db_path=None):
    """各模块最近一次成功抓取时间，返回 {module_slug: fetched_at}。"""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT module_slug, MAX(fetched_at) AS t FROM fetch_runs
               WHERE status = 'ok' AND module_slug IS NOT NULL
               GROUP BY module_slug"""
        ).fetchall()
        return {r["module_slug"]: r["t"] for r in rows}


# ---------- 设置 ----------

def get_setting(key, default=None, db_path=None):
    with _connect(db_path) as conn:
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        return row["value"] if row else default


def set_setting(key, value, db_path=None):
    with _DB_LOCK, _connect(db_path) as conn:
        conn.execute(
            "INSERT INTO settings(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, str(value)),
        )
