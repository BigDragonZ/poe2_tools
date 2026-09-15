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

from . import db, scraper, scheduler
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
