"""Shared local-time helpers for reminder and schedule logic."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo


LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")
WEEKDAY_CN = {
    0: "周一",
    1: "周二",
    2: "周三",
    3: "周四",
    4: "周五",
    5: "周六",
    6: "周日",
}


def get_now_local() -> datetime:
    return datetime.now(LOCAL_TIMEZONE)


def get_today_local() -> date:
    return get_now_local().date()


def get_tomorrow_local() -> date:
    return (get_now_local() + timedelta(days=1)).date()


def get_weekday_cn(target_date: date) -> str:
    return WEEKDAY_CN[target_date.weekday()]
