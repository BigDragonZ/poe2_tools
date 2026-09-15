"""APScheduler 定时抓取：开服前 2 周（可配阈值）每天抓，之后每周抓。

规则存 settings 表：sched_enabled / sched_daily_time / sched_weekly_day /
sched_weekly_time / sched_switch_days。
实现方式：常驻日级与周级两个 cron 任务，触发时按当前赛季开服天数决定是否执行，
阈值跨越无需人工干预。
"""

from datetime import date

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import db
from .service import start_refresh

DEFAULT_SCHEDULE = {
    "sched_enabled": "0",
    "sched_daily_time": "08:00",
    "sched_weekly_day": "1",      # 0=周一 … 6=周日
    "sched_weekly_time": "08:00",
    "sched_switch_days": "14",
}

_scheduler = None


def get_schedule_config(db_path=None):
    """读取定时配置，缺省值补全，返回带类型的 dict。"""
    cfg = {k: db.get_setting(k, v, db_path=db_path) for k, v in DEFAULT_SCHEDULE.items()}
    return {
        "enabled": cfg["sched_enabled"] == "1",
        "daily_time": cfg["sched_daily_time"],
        "weekly_day": int(cfg["sched_weekly_day"]),
        "weekly_time": cfg["sched_weekly_time"],
        "switch_days": int(cfg["sched_switch_days"]),
    }


def save_schedule_config(enabled, daily_time, weekly_day, weekly_time, switch_days,
                         db_path=None):
    db.set_setting("sched_enabled", "1" if enabled else "0", db_path=db_path)
    db.set_setting("sched_daily_time", daily_time, db_path=db_path)
    db.set_setting("sched_weekly_day", weekly_day, db_path=db_path)
    db.set_setting("sched_weekly_time", weekly_time, db_path=db_path)
    db.set_setting("sched_switch_days", switch_days, db_path=db_path)


def _season_age_days():
    """当前赛季开服天数（开服当天 = 1）；无赛季返回 None。"""
    season = db.get_current_season()
    if season is None:
        return None
    return (date.today() - date.fromisoformat(season["start_date"])).days + 1


def _job_daily():
    cfg = get_schedule_config()
    age = _season_age_days()
    if age is not None and age <= cfg["switch_days"]:
        start_refresh(module_slug=None)


def _job_weekly():
    cfg = get_schedule_config()
    age = _season_age_days()
    if age is not None and age > cfg["switch_days"]:
        start_refresh(module_slug=None)


def _parse_hhmm(text, default="08:00"):
    try:
        hh, mm = text.split(":")
        return int(hh), int(mm)
    except (ValueError, AttributeError):
        hh, mm = default.split(":")
        return int(hh), int(mm)


def reschedule():
    """按当前配置重建定时任务。"""
    global _scheduler
    if _scheduler is None:
        _scheduler = BackgroundScheduler()
        _scheduler.start()
    _scheduler.remove_all_jobs()
    cfg = get_schedule_config()
    if not cfg["enabled"]:
        return
    hh, mm = _parse_hhmm(cfg["daily_time"])
    _scheduler.add_job(_job_daily, CronTrigger(hour=hh, minute=mm),
                       id="daily_fetch", replace_existing=True)
    hh, mm = _parse_hhmm(cfg["weekly_time"])
    # APScheduler day_of_week：0=周一
    _scheduler.add_job(_job_weekly, CronTrigger(day_of_week=cfg["weekly_day"],
                                                hour=hh, minute=mm),
                       id="weekly_fetch", replace_existing=True)


def shutdown():
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
