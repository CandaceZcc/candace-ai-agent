"""Schedule file helpers for tomorrow-course reminders."""

from __future__ import annotations

import json
import os
import traceback
from datetime import date, datetime, timedelta

from apps.qq_ai_bridge.services.time_utils import get_now_local, get_tomorrow_local, get_weekday_cn


WEEKDAY_NAMES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}

DEFAULT_SCHEDULE = {
    "Monday": [],
    "Tuesday": [],
    "Wednesday": [],
    "Thursday": [],
    "Friday": [],
}


def ensure_schedule_file(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.exists(path):
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(DEFAULT_SCHEDULE, fh, ensure_ascii=False, indent=2)


def load_schedule(path: str) -> dict:
    ensure_schedule_file(path)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if not isinstance(data, dict):
            raise ValueError("schedule root must be object")
        return data
    except Exception:
        print(f"[SCHEDULE] failed load path={path}")
        traceback.print_exc()
        return dict(DEFAULT_SCHEDULE)


def query_tomorrow_schedule(schedule_path: str, now: datetime | None = None) -> dict:
    now_local = now.astimezone(get_now_local().tzinfo) if now else get_now_local()
    tomorrow_date = (now_local + timedelta(days=1)).date()
    weekday = tomorrow_date.weekday()
    weekday_cn = get_weekday_cn(tomorrow_date)
    schedule = load_schedule(schedule_path)
    courses = schedule.get(WEEKDAY_NAMES[weekday], []) if weekday < 5 else []
    return {
        "date": tomorrow_date.isoformat(),
        "weekday_cn": weekday_cn,
        "is_weekend": weekday >= 5,
        "courses": courses,
    }


def format_tomorrow_schedule_reply(schedule_info: dict) -> str:
    weekday_cn = schedule_info["weekday_cn"]
    if schedule_info["is_weekend"]:
        return f"明天是{weekday_cn}，好好休息。"

    lines = [f"明天是{weekday_cn}。"]
    courses = schedule_info.get("courses", [])
    if not courses:
        lines.append("明天暂无课程安排。")
        return "\n".join(lines)

    lines.append("明天课程：")
    for idx, course in enumerate(courses, start=1):
        if isinstance(course, dict):
            start = str(course.get("start", "")).strip()
            end = str(course.get("end", "")).strip()
            name = str(course.get("name", "")).strip()
            location = str(course.get("location", "")).strip()
            line = f"{idx}. {start}-{end} {name}".strip()
            if location:
                line = f"{line} @ {location}"
        else:
            line = f"{idx}. {course}"
        lines.append(line)
    return "\n".join(lines)


def build_tomorrow_schedule_message(schedule_path: str, now: datetime | None = None) -> str:
    return format_tomorrow_schedule_reply(query_tomorrow_schedule(schedule_path, now=now))
