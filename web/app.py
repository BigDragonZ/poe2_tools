"""FastAPI 入口：POE2 经济记录 Web 应用。

启动：uv run python -m web.app（端口 8321）。
"""

from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, scraper, scheduler, trading
from .service import (get_library_status, get_refresh_status,
                      start_library_scrape, start_refresh)

STATIC_DIR = Path(__file__).parent / "static"
ICONS_DIR = STATIC_DIR / "icons"
PORT = 8321


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    ICONS_DIR.mkdir(parents=True, exist_ok=True)
    scheduler.reschedule()
    yield
    scheduler.shutdown()


app = FastAPI(title="POE2 经济记录", lifespan=lifespan)


ICONS_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/icons", StaticFiles(directory=str(ICONS_DIR)), name="icons")


# ---------- 页面 ----------

@app.get("/")
def index():
    return FileResponse(str(STATIC_DIR / "index.html"))


# ---------- 赛季 ----------

class SeasonIn(BaseModel):
    name: str
    start_date: str  # YYYY-MM-DD


@app.get("/api/seasons")
def api_list_seasons():
    return db.list_seasons()


@app.post("/api/seasons", status_code=201)
def api_create_season(body: SeasonIn):
    try:
        date.fromisoformat(body.start_date)
    except ValueError:
        raise HTTPException(400, "开服日期格式应为 YYYY-MM-DD")
    season_id = db.create_season(body.name, body.start_date)
    return db.get_season(season_id)


@app.put("/api/seasons/{season_id}")
def api_update_season(season_id: int, body: SeasonIn):
    if db.get_season(season_id) is None:
        raise HTTPException(404, "赛季不存在")
    try:
        date.fromisoformat(body.start_date)
    except ValueError:
        raise HTTPException(400, "开服日期格式应为 YYYY-MM-DD")
    db.update_season(season_id, body.name, body.start_date)
    return db.get_season(season_id)


# ---------- 模块 ----------

@app.get("/api/modules")
def api_list_modules():
    """模块列表；数据库为空时用内置清单兜底（尚未抓取时也能渲染菜单）。"""
    modules = db.list_modules()
    if not modules:
        return [{"id": None, "slug": slug, "name_zh": name, "icon_path": None}
                for slug, name in scraper.MODULES]
    return modules


# ---------- 经济数据 ----------

def _season_or_404(season_id):
    season = db.get_season(season_id)
    if season is None:
        raise HTTPException(404, "赛季不存在")
    return season


@app.get("/api/economy/{module_slug}")
def api_economy(module_slug: str, season_id: int, day: int | None = None):
    """某模块物品快照列表。day 省略 = 最新快照；否则取该开服天数当天最新一次。"""
    season = _season_or_404(season_id)
    start = date.fromisoformat(season["start_date"])
    target_date = None
    if day is not None:
        target_date = (start + timedelta(days=day - 1)).isoformat()
    used_date, rows = db.get_module_snapshots(module_slug, season_id, target_date)
    used_day = None
    fetched_at = None
    if used_date:
        used_day = (date.fromisoformat(used_date) - start).days + 1
        if rows:
            fetched_at = max(r["fetched_at"] for r in rows)
    today_day = (date.today() - start).days + 1
    ref_slugs = {r["ref_currency"] for r in rows if r.get("ref_currency")}
    return {
        "season": season,
        "module_slug": module_slug,
        "day": used_day,
        "today_day": today_day,
        "fetched_at": fetched_at,
        "items": rows,
        "ref_icons": db.get_item_icons_by_slugs(sorted(ref_slugs)),
    }


@app.get("/api/economy/{module_slug}/days")
def api_economy_days(module_slug: str, season_id: int):
    """该模块有数据的开服天数列表。"""
    season = _season_or_404(season_id)
    days = db.list_snapshot_days(module_slug, season_id, season["start_date"])
    return {"days": days}


# ---------- 刷新 ----------

@app.post("/api/refresh/{module_slug}")
def api_refresh_module(module_slug: str):
    """手动刷新当前模块（后台线程执行）。"""
    if module_slug not in scraper.MODULE_SLUGS:
        raise HTTPException(404, "未知模块")
    if not start_refresh(module_slug):
        raise HTTPException(409, "已有刷新任务进行中")
    return {"ok": True, "module_slug": module_slug}


@app.post("/api/refresh_all")
def api_refresh_all():
    """全量刷新（定时任务用，也可手动触发）。"""
    if not start_refresh(None):
        raise HTTPException(409, "已有刷新任务进行中")
    return {"ok": True}


@app.get("/api/refresh_status")
def api_refresh_status():
    return get_refresh_status()


# ---------- 定时配置 ----------

class ScheduleIn(BaseModel):
    enabled: bool
    daily_time: str = "08:00"
    weekly_day: int = 1
    weekly_time: str = "08:00"
    switch_days: int = 14


@app.get("/api/schedule")
def api_get_schedule():
    return scheduler.get_schedule_config()


@app.put("/api/schedule")
def api_put_schedule(body: ScheduleIn):
    if not (0 <= body.weekly_day <= 6):
        raise HTTPException(400, "每周星期几取值 0-6")
    if body.switch_days < 1:
        raise HTTPException(400, "切换阈值天数必须 >= 1")
    scheduler.save_schedule_config(body.enabled, body.daily_time, body.weekly_day,
                                   body.weekly_time, body.switch_days)
    scheduler.reschedule()
    return scheduler.get_schedule_config()


# ---------- 交易（市场比例） ----------

class GoldValuesIn(BaseModel):
    exalted: float | None = None
    chaos: float | None = None
    divine: float | None = None


def _unit_labels(rates):
    """rates 出现的全部单位 → {"zh", "en"}（单位双名展示用）。

    默认三通货用 BASE_LABELS/BASE_NAMES_EN；item:X 单位按归一化名
    （canon_item_name）匹配 items/item_info 取中文名，查不到 zh 为 None；
    en 为游戏内英文名。
    """
    canon_zh = {trading.canon_item_name(n): zh
                for n, zh in db.get_names_zh_by_names_en().items()}
    units = set(trading.BASE_CURRENCIES)
    for r in rates:
        units.add(r["from_unit"])
        units.add(r["to_unit"])
    labels = {}
    for u in sorted(units):
        if u in trading.BASE_LABELS:
            labels[u] = {"zh": trading.BASE_LABELS[u], "en": trading.BASE_NAMES_EN[u]}
        elif trading.is_item_unit(u):
            name = u[len(trading.ITEM_PREFIX):]
            labels[u] = {"zh": canon_zh.get(trading.canon_item_name(name)), "en": name}
        else:
            labels[u] = {"zh": None, "en": u}
    return labels


def _trade_unit_icons(latest):
    """基础通货按 slug、物品按中文名查本地图标，返回 {unit: icon_path}。"""
    icons = db.get_item_icons_by_slugs(trading.BASE_CURRENCIES)
    item_names = sorted({
        u[len(trading.ITEM_PREFIX):]
        for r in latest for u in (r["from_unit"], r["to_unit"])
        if trading.is_item_unit(u)
    })
    for name, path in db.get_item_icons_by_names(item_names).items():
        icons[trading.item_unit(name)] = path
    return icons


def _gold_values(rates=None):
    """各通货 Currency Exchange 值（金币/个）：手动覆盖优先，否则取信息库抓取值。

    三默认通货之外，信息库中所有有金币消耗的物品以 item:英文名 为单位一并纳入；
    rates 中出现的 item: 单位按归一化名称（canon_item_name）匹配信息库，
    抹平撇号等标点差异（如 Perfect Jewellers Orb ↔ Perfect Jeweller's Orb）。
    返回 {unit: {"value": float|None, "source": "manual"|"library"|None}}。
    """
    library = db.get_gold_costs_by_slugs(trading.BASE_CURRENCIES)
    result = {}
    for u in trading.BASE_CURRENCIES:
        raw = db.get_setting("trade_gold_value:" + u)
        if raw:
            result[u] = {"value": float(raw), "source": "manual"}
        elif library.get(u):
            result[u] = {"value": library[u], "source": "library"}
        else:
            result[u] = {"value": None, "source": None}
    library_items = db.get_gold_costs_by_names_en()
    canon_costs = {trading.canon_item_name(n): c for n, c in library_items.items()}
    item_names = set(library_items)
    for r in rates or []:
        for u in (r["from_unit"], r["to_unit"]):
            if trading.is_item_unit(u):
                item_names.add(u[len(trading.ITEM_PREFIX):])
    for name in sorted(item_names):
        u = trading.ITEM_PREFIX + name
        raw = db.get_setting("trade_gold_value:" + u)
        if raw:
            result[u] = {"value": float(raw), "source": "manual"}
            continue
        cost = canon_costs.get(trading.canon_item_name(name))
        result[u] = ({"value": cost, "source": "library"} if cost
                     else {"value": None, "source": None})
    return result


@app.get("/api/trade/state")
def api_trade_state(category: str = "default"):
    """交易页全量状态：最新汇率、每轮口径最佳套利方案（含独立复核）、
    套利机会列表、单位双名与图标。

    套利核心是金币换通货（不关注持仓）：方案以 1 单位起点通货为一轮，
    收益看通货互换价差，效率看每 1 万金币净得多少神圣当量。
    category 对应交易菜单三级页面：default（默认）/ custom（指定）/ auto（自动），
    数据由游玩工具交易模块对应子标签抓取同步（桌面端直接写库，本页面只读展示）。
    """
    if category not in db.TRADE_CATEGORIES:
        raise HTTPException(400, "category 取值 default|custom|auto")
    latest = db.latest_trade_rates(category)
    gold_values = _gold_values(latest)
    gv = {u: g["value"] for u, g in gold_values.items() if g["value"]}
    return {
        "category": category,
        "latest": latest,
        "arb_plan": trading.best_arbitrage_round(latest, gv),
        "opportunities": trading.arbitrage_opportunities(latest, gv)[:10],
        "unit_labels": _unit_labels(latest),
        "unit_icons": _trade_unit_icons(latest),
    }


@app.put("/api/trade/gold_values")
def api_put_gold_values(body: GoldValuesIn):
    """手动设置/清除通货的 Currency Exchange 值（金币/个）。None 或 <=0 = 清除手动覆盖。"""
    for u in trading.BASE_CURRENCIES:
        v = getattr(body, u)
        db.set_setting("trade_gold_value:" + u, str(v) if v and v > 0 else "")
    return _gold_values()


# ---------- 信息库 ----------

@app.get("/api/library")
def api_library(search: str | None = None, module_slug: str | None = None):
    """信息库物品列表：中英文名称、模块、wiki 链接、Currency Exchange 金币消耗。"""
    return {"items": db.list_library_items(search=search, module_slug=module_slug)}


@app.post("/api/library/refresh")
def api_library_refresh(mode: str = "missing"):
    """后台抓取 wiki 信息（金币消耗）。mode=missing 只抓缺失，mode=all 全部重抓。"""
    if mode not in ("missing", "all"):
        raise HTTPException(400, "mode 取值 missing|all")
    if not start_library_scrape(mode):
        raise HTTPException(409, "已有信息库抓取任务进行中")
    return {"ok": True, "mode": mode}


@app.get("/api/library/status")
def api_library_status():
    return get_library_status()


# ---------- 元信息 ----------

@app.get("/api/meta")
def api_meta():
    """汇率与各模块最近刷新时间。"""
    raw = db.get_setting("chaos_per_divine")
    return {
        "chaos_per_divine": float(raw) if raw else None,
        "module_last_fetch": db.latest_fetch_time_by_module(),
        "recent_runs": db.list_recent_fetch_runs(10),
    }


if __name__ == "__main__":
    import uvicorn

    db.init_db()
    uvicorn.run(app, host="127.0.0.1", port=PORT)
