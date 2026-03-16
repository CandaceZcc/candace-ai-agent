"""Schedule query helpers."""

from __future__ import annotations

import json
import os
import traceback
from datetime import date, datetime, timedelta

from apps.qq_ai_bridge.services.time_utils import get_now_local, get_today_local, get_tomorrow_local, get_weekday_cn


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


def detect_schedule_intent(text: str) -> str | None:
    normalized = str(text or "").strip()
    if any(token in normalized for token in ("明天有什么课或者提醒", "明天有什么课和提醒", "明天有课和提醒吗", "明天有提醒和课吗")):
        return "tomorrow_overview"
    if any(token in normalized for token in ("明天有什么课", "明天有课吗", "明天课程", "明天有什么课呢")):
        return "tomorrow_schedule"
    if any(token in normalized for token in ("今天有什么课", "今天有课吗", "今天课程")):
        return "today_schedule"
    return None


def query_schedule_for_date(schedule_path: str, target_date: date) -> dict:
    print(f"[SCHEDULE] query target_date={target_date.isoformat()}")
    weekday = target_date.weekday()
    weekday_cn = get_weekday_cn(target_date)
    schedule = load_schedule(schedule_path)
    courses = schedule.get(WEEKDAY_NAMES[weekday], []) if weekday < 5 else []
    return {
        "date": target_date.isoformat(),
        "weekday_cn": weekday_cn,
        "is_weekend": weekday >= 5,
        "courses": courses,
    }


def query_today_schedule(schedule_path: str, now: datetime | None = None) -> dict:
    now_local = now.astimezone(get_now_local().tzinfo) if now else get_now_local()
    return query_schedule_for_date(schedule_path, now_local.date())


def query_tomorrow_schedule(schedule_path: str, now: datetime | None = None) -> dict:
    now_local = now.astimezone(get_now_local().tzinfo) if now else get_now_local()
    return query_schedule_for_date(schedule_path, (now_local + timedelta(days=1)).date())


def format_schedule_reply(schedule_info: dict, prefix: str) -> str:
    weekday_cn = schedule_info["weekday_cn"]
    if schedule_info["is_weekend"]:
        return f"{prefix}是{weekday_cn}，好好休息。"

    lines = [f"{prefix}是{weekday_cn}。"]
    courses = schedule_info.get("courses", [])
    if not courses:
        lines.append(f"{prefix}暂无课程安排。")
        return "\n".join(lines)

    lines.append(f"{prefix}课程：")
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


def format_today_schedule_reply(schedule_info: dict) -> str:
    return format_schedule_reply(schedule_info, "今天")


def format_tomorrow_schedule_reply(schedule_info: dict) -> str:
    return format_schedule_reply(schedule_info, "明天")


def build_tomorrow_schedule_message(schedule_path: str, now: datetime | None = None) -> str:
    return format_tomorrow_schedule_reply(query_tomorrow_schedule(schedule_path, now=now))
