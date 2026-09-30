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
from .service import get_refresh_status, start_refresh

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


# ---------- 交易助手 ----------

class TradeRateIn(BaseModel):
    from_unit: str
    to_unit: str
    amount_from: float
    amount_to: float
    side: str = "sell"  # buy = 市场买入（付金币），sell = 卖出（免金币）


class GoldValuesIn(BaseModel):
    exalted: float | None = None
    chaos: float | None = None
    divine: float | None = None


def _valid_unit(unit):
    if unit in trading.BASE_CURRENCIES:
        return True
    return trading.is_item_unit(unit) and len(unit) > len(trading.ITEM_PREFIX)


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


def _gold_values():
    """各通货 Currency Exchange 值（金币/个）：手动覆盖优先，否则取信息库抓取值。

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
    return result


@app.get("/api/trade/state")
def api_trade_state():
    """交易页全量状态：最新汇率、历史、最优方案、套利环、金币转化比例。"""
    latest = db.latest_trade_rates()
    gold_values = _gold_values()
    gv = {u: g["value"] for u, g in gold_values.items() if g["value"]}
    best = {}
    for src in trading.BASE_CURRENCIES:
        for dst in trading.BASE_CURRENCIES:
            if src == dst:
                continue
            rate, path = trading.best_conversion(latest, src, dst, gv)
            if rate is not None:
                best[src + ">" + dst] = {"rate": rate, "path": path}
    return {
        "base_currencies": [{"unit": u, "label": trading.BASE_LABELS[u]}
                            for u in trading.BASE_CURRENCIES],
        "latest": latest,
        "history": db.list_trade_rates(30),
        "best": best,
        "cycles": trading.find_profitable_cycles(latest, gv),
        "gold_values": gold_values,
        "gold_conversion": trading.gold_conversion(latest, gv),
        "unit_icons": _trade_unit_icons(latest),
        "known_items": db.list_item_names(),
    }


@app.post("/api/trade/rates", status_code=201)
def api_add_trade_rate(body: TradeRateIn):
    if not (_valid_unit(body.from_unit) and _valid_unit(body.to_unit)):
        raise HTTPException(400, "无效的兑换单位")
    if body.from_unit == body.to_unit:
        raise HTTPException(400, "兑换双方不能相同")
    if body.amount_from <= 0 or body.amount_to <= 0:
        raise HTTPException(400, "数量必须为正数")
    if body.side not in ("buy", "sell"):
        raise HTTPException(400, "side 取值 buy|sell")
    rate_id = db.add_trade_rate(body.from_unit, body.to_unit,
                                body.amount_from, body.amount_to, body.side)
    return {"id": rate_id}


@app.delete("/api/trade/rates/{rate_id}")
def api_delete_trade_rate(rate_id: int):
    if not db.delete_trade_rate(rate_id):
        raise HTTPException(404, "汇率记录不存在")
    return {"ok": True}


@app.put("/api/trade/gold_values")
def api_put_gold_values(body: GoldValuesIn):
    """手动设置/清除通货的 Currency Exchange 值（金币/个）。None 或 <=0 = 清除手动覆盖。"""
    for u in trading.BASE_CURRENCIES:
        v = getattr(body, u)
        db.set_setting("trade_gold_value:" + u, str(v) if v and v > 0 else "")
    return _gold_values()


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
