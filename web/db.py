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
CREATE TABLE IF NOT EXISTS trade_rates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    from_unit TEXT NOT NULL,
    to_unit TEXT NOT NULL,
    amount_from REAL NOT NULL,
    amount_to REAL NOT NULL,
    side TEXT NOT NULL DEFAULT 'sell',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS item_info (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    item_id INTEGER UNIQUE NOT NULL REFERENCES items(id),
    wiki_url TEXT,
    gold_cost REAL,
    name_zh TEXT,
    name_en TEXT,
    fetched_at TEXT NOT NULL
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
    """建表（幂等）；对已存在的库做轻量迁移。"""
    with _DB_LOCK, _connect(db_path) as conn:
        conn.executescript(_SCHEMA)
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(trade_rates)")]
        if "side" not in cols:
            conn.execute("ALTER TABLE trade_rates ADD COLUMN side TEXT NOT NULL DEFAULT 'sell'")


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


# ---------- 交易汇率 ----------

def add_trade_rate(from_unit, to_unit, amount_from, amount_to, side="sell", db_path=None):
    """录入一条手动观测的兑换比例（from_unit * amount_from = to_unit * amount_to）。

    side：buy = 市场买入（需付金币），sell = 卖出（免金币）。
    """
    with _DB_LOCK, _connect(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO trade_rates(from_unit, to_unit, amount_from, amount_to, side, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (from_unit, to_unit, amount_from, amount_to, side, _now()),
        )
        return cur.lastrowid


def list_trade_rates(limit=50, db_path=None):
    """最近的汇率记录（新→旧）。"""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM trade_rates ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def latest_trade_rates(db_path=None):
    """每个 (from_unit, to_unit, side) 方向最新一条汇率。"""
    with _connect(db_path) as conn:
        rows = conn.execute(
            """SELECT t.* FROM trade_rates t
               WHERE t.id = (
                   SELECT MAX(t2.id) FROM trade_rates t2
                   WHERE t2.from_unit = t.from_unit AND t2.to_unit = t.to_unit
                     AND t2.side = t.side)
               ORDER BY t.id DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


def delete_trade_rate(rate_id, db_path=None):
    with _DB_LOCK, _connect(db_path) as conn:
        cur = conn.execute("DELETE FROM trade_rates WHERE id = ?", (rate_id,))
        return cur.rowcount > 0


def list_item_names(limit=500, db_path=None):
    """已知物品名（供交易页物品输入联想）。"""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT DISTINCT name_zh FROM items ORDER BY name_zh LIMIT ?", (limit,)
        ).fetchall()
        return [r["name_zh"] for r in rows]


def get_item_icons_by_names(names, db_path=None):
    """按物品中文名查本地图标路径，返回 {name_zh: icon_path}。"""
    if not names:
        return {}
    placeholders = ",".join("?" for _ in names)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT name_zh, icon_path FROM items WHERE name_zh IN ({placeholders}) "
            "AND icon_path IS NOT NULL GROUP BY name_zh",
            list(names),
        ).fetchall()
        return {r["name_zh"]: r["icon_path"] for r in rows}


# ---------- 信息库 ----------

def get_gold_costs_by_slugs(slugs, db_path=None):
    """按物品 slug 查信息库的 Currency Exchange 金币消耗，返回 {slug: gold_cost}。

    item_info 表不存在（信息库功能未建库）时返回空，退化为纯手动模式。
    """
    if not slugs:
        return {}
    placeholders = ",".join("?" for _ in slugs)
    with _connect(db_path) as conn:
        exists = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'item_info'"
        ).fetchone()
        if exists is None:
            return {}
        rows = conn.execute(
            f"""SELECT i.slug, info.gold_cost FROM items i
                JOIN item_info info ON info.item_id = i.id
                WHERE i.slug IN ({placeholders}) AND info.gold_cost IS NOT NULL
                GROUP BY i.slug""",
            list(slugs),
        ).fetchall()
        return {r["slug"]: r["gold_cost"] for r in rows}


def upsert_item_info(item_id, wiki_url, gold_cost, name_zh, name_en, db_path=None):
    """写入/更新物品的 wiki 信息（金币消耗与 wiki 端中英文名）。"""
    with _DB_LOCK, _connect(db_path) as conn:
        conn.execute(
            """INSERT INTO item_info(item_id, wiki_url, gold_cost, name_zh, name_en, fetched_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(item_id) DO UPDATE SET
                   wiki_url = excluded.wiki_url,
                   gold_cost = excluded.gold_cost,
                   name_zh = excluded.name_zh,
                   name_en = excluded.name_en,
                   fetched_at = excluded.fetched_at""",
            (item_id, wiki_url, gold_cost, name_zh, name_en, _now()),
        )


def list_wiki_scrape_targets(only_missing=True, db_path=None):
    """有 wiki 链接的物品抓取清单。only_missing=True 时只取尚未抓过 wiki 信息的。"""
    sql = """SELECT i.id AS item_id, i.wiki_slug FROM items i
             LEFT JOIN item_info info ON info.item_id = i.id
             WHERE i.wiki_slug IS NOT NULL AND i.wiki_slug != ''"""
    if only_missing:
        sql += " AND info.item_id IS NULL"
    sql += " ORDER BY i.id"
    with _connect(db_path) as conn:
        rows = conn.execute(sql).fetchall()
        return [dict(r) for r in rows]


def list_library_items(search=None, module_slug=None, db_path=None):
    """信息库物品列表：中英文名称、所属模块、wiki 链接、金币消耗。

    search 非空时对物品中/英文名、模块中/英文名（slug）、wiki_slug 做模糊检索。
    """
    conditions = []
    params = []
    if module_slug:
        conditions.append("m.slug = ?")
        params.append(module_slug)
    if search and search.strip():
        kw = "%" + search.strip() + "%"
        conditions.append(
            "(i.name_zh LIKE ? OR i.name_en LIKE ?"
            " OR info.name_zh LIKE ? OR info.name_en LIKE ?"
            " OR m.name_zh LIKE ? OR m.slug LIKE ?"
            " OR i.slug LIKE ? OR i.wiki_slug LIKE ?)"
        )
        params.extend([kw] * 8)
    where = ("WHERE " + " AND ".join(conditions)) if conditions else ""
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"""SELECT i.id AS item_id, i.slug, i.icon_path, i.wiki_slug,
                       m.slug AS module_slug, m.name_zh AS module_name_zh,
                       COALESCE(info.name_zh, i.name_zh) AS name_zh,
                       COALESCE(info.name_en, i.name_en) AS name_en,
                       info.wiki_url, info.gold_cost, info.fetched_at AS info_fetched_at
                FROM items i
                JOIN modules m ON m.id = i.module_id
                LEFT JOIN item_info info ON info.item_id = i.id
                {where}
                ORDER BY m.id, i.slug""",
            params,
        ).fetchall()
        return [dict(r) for r in rows]


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
