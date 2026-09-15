"""抓取编排：手动刷新（单模块/全量）与入库流程，供 API 与定时任务共用。"""

import threading
import time
from datetime import datetime

from . import db, scraper
from .icons import localize_icon

# 刷新进度（内存态，供前端轮询）
_STATUS_LOCK = threading.Lock()
_REFRESH_STATUS = {
    "running": False,
    "mode": None,           # "module" / "all"
    "current_module": None,
    "done": 0,
    "total": 0,
    "started_at": None,
    "finished_at": None,
    "error": None,
}


def get_refresh_status():
    with _STATUS_LOCK:
        return dict(_REFRESH_STATUS)


def _set_status(**kwargs):
    with _STATUS_LOCK:
        _REFRESH_STATUS.update(kwargs)


def is_running():
    with _STATUS_LOCK:
        return _REFRESH_STATUS["running"]


def _store_module_result(module_slug, season_id, items, db_path=None):
    """把一个模块的解析结果入库，返回写入快照条数。"""
    module = db.get_module_by_slug(module_slug, db_path=db_path)
    if module is None:
        db.upsert_module(module_slug, scraper.MODULE_NAMES.get(module_slug, module_slug),
                         db_path=db_path)
        module = db.get_module_by_slug(module_slug, db_path=db_path)

    chaos_per_divine = None
    raw = db.get_setting("chaos_per_divine", db_path=db_path)
    if raw:
        chaos_per_divine = float(raw)

    # 抓 Currency 模块时同步更新混沌⇄神圣汇率
    if module_slug == "Economy_Currency":
        rate = scraper.extract_chaos_per_divine(items)
        if rate:
            chaos_per_divine = rate
            db.set_setting("chaos_per_divine", rate, db_path=db_path)

    fetched_at = datetime.now().isoformat(timespec="seconds")
    count = 0
    for item in items:
        icon_path = None
        try:
            icon_path = localize_icon(item.get("icon_url"))
        except Exception:
            icon_path = None  # 图标下载失败不阻断入库
        item_id = db.upsert_item(
            module["id"], item["slug"], item["name_zh"], item.get("name_en"),
            icon_path, item.get("wiki_slug"), db_path=db_path,
        )
        price_divine, price_chaos = scraper.compute_prices(
            item.get("ref_currency"), item.get("ref_amount"),
            item.get("item_amount"), chaos_per_divine,
        )
        snap = dict(item)
        snap["price_divine"] = price_divine
        snap["price_chaos"] = price_chaos
        db.insert_snapshot(item_id, season_id, fetched_at, snap, db_path=db_path)
        count += 1
    return count


def _update_module_cards(module_cards, db_path=None):
    """从页面卡片同步 14 个模块的名称与本地图标。"""
    for card in module_cards:
        icon_path = None
        try:
            icon_path = localize_icon(card.get("icon_url"))
        except Exception:
            icon_path = None
        db.upsert_module(card["slug"], card["name_zh"], icon_path, db_path=db_path)


def refresh_module(module_slug, season_id=None, db_path=None):
    """刷新单个模块并入库。返回物品条数。"""
    if season_id is None:
        season = db.get_current_season(db_path=db_path)
        if season is None:
            raise RuntimeError("尚未录入赛季，请先在页面上新增赛季")
        season_id = season["id"]
    items, module_cards = scraper.fetch_module_items(module_slug)
    if module_cards:
        _update_module_cards(module_cards, db_path=db_path)
    count = _store_module_result(module_slug, season_id, items, db_path=db_path)
    db.insert_fetch_run(season_id, module_slug, "ok", f"抓取 {count} 条", db_path=db_path)
    return count


def _run_refresh(module_slug=None):
    """后台线程入口：module_slug 为 None 表示全量刷新。"""
    mode = "all" if module_slug is None else "module"
    total = len(scraper.MODULE_SLUGS) if module_slug is None else 1
    _set_status(running=True, mode=mode, current_module=None, done=0,
                total=total, started_at=datetime.now().isoformat(timespec="seconds"),
                finished_at=None, error=None)
    try:
        season = db.get_current_season()
        if season is None:
            raise RuntimeError("尚未录入赛季，请先在页面上新增赛季")
        if module_slug is not None:
            _set_status(current_module=module_slug)
            refresh_module(module_slug, season_id=season["id"])
            _set_status(done=1)
        else:
            for i, slug in enumerate(scraper.MODULE_SLUGS):
                _set_status(current_module=slug)
                try:
                    refresh_module(slug, season_id=season["id"])
                except Exception as exc:
                    db.insert_fetch_run(season["id"], slug, "error", str(exc))
                _set_status(done=i + 1)
                if i < total - 1:
                    time.sleep(scraper.REQUEST_INTERVAL)
            db.insert_fetch_run(season["id"], None, "ok", "全量刷新完成")
        _set_status(running=False, finished_at=datetime.now().isoformat(timespec="seconds"))
    except Exception as exc:
        _set_status(running=False, error=str(exc),
                    finished_at=datetime.now().isoformat(timespec="seconds"))


def start_refresh(module_slug=None):
    """启动后台刷新线程。已在运行返回 False，否则返回 True。"""
    if is_running():
        return False
    thread = threading.Thread(target=_run_refresh, args=(module_slug,), daemon=True)
    thread.start()
    return True
