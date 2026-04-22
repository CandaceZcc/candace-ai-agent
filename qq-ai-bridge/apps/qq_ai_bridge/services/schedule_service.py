"""Schedule query helpers."""

from __future__ import annotations

import json
import os
import traceback
from datetime import date, datetime, timedelta

from apps.qq_ai_bridge.logging.bridge_log import log_change
from apps.qq_ai_bridge.services.time_utils import get_now_local, get_weekday_cn

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

TODAY_SCHEDULE_EXACT = (
    "今天课表",
    "今日课表",
    "今天课程",
    "今日课程",
    "查今天课表",
    "看今天课表",
    "有什么课",
)
TODAY_SCHEDULE_CONTAINS = (
    "今天有什么课",
    "今天有课吗",
    "今天课表",
    "今日课表",
    "今天课程安排",
    "今日课程安排",
    "看看今天课表",
    "查询今天课表",
    "帮我看看今天课表",
    "今天的课表",
    "今日的课表",
)
TOMORROW_SCHEDULE_EXACT = (
    "明天课表",
    "明日课表",
    "明天课程",
    "明日课程",
    "查明天课表",
    "看明天课表",
)
TOMORROW_SCHEDULE_CONTAINS = (
    "明天有什么课",
    "明天有课吗",
    "明天课表",
    "明日课表",
    "明天课程安排",
    "明日课程安排",
    "看看明天课表",
    "查询明天课表",
    "帮我看看明天课表",
    "明天的课表",
    "明日的课表",
)


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
    normalized = str(text or "").strip().replace(" ", "")
    if any(
        token in normalized
        for token in (
            "明天有什么课或者提醒",
            "明天有什么课和提醒",
            "明天有课和提醒吗",
            "明天有提醒和课吗",
        )
    ):
        return "tomorrow_overview"
    if normalized in TOMORROW_SCHEDULE_EXACT or any(
        token in normalized for token in TOMORROW_SCHEDULE_CONTAINS
    ):
        return "tomorrow_schedule"
    if normalized in TODAY_SCHEDULE_EXACT or any(token in normalized for token in TODAY_SCHEDULE_CONTAINS):
        return "today_schedule"
    return None


def query_schedule_for_date(schedule_path: str, target_date: date) -> dict:
    weekday = target_date.weekday()
    weekday_cn = get_weekday_cn(target_date)
    schedule = load_schedule(schedule_path)
    courses = schedule.get(WEEKDAY_NAMES[weekday], []) if weekday < 5 else []
    snapshot = (target_date.isoformat(), WEEKDAY_NAMES[weekday], len(courses))
    log_change(
        "SCHEDULE",
        f"query:{schedule_path}",
        snapshot,
        "query target=%s weekday=%s course_count=%d",
        *snapshot,
    )
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
        lines.append(f"按本地课表，{prefix}暂无课程安排。")
        return "\n".join(lines)

    lines.append(f"{prefix}课程：")
    for idx, course in enumerate(courses, start=1):
        if isinstance(course, dict):
            start = str(course.get("start", "")).strip()
            end = str(course.get("end", "")).strip()
            name = str(course.get("name", "")).strip()
            course_code = str(course.get("course_code", "")).strip()
            category = str(course.get("category", "")).strip()
            location = str(course.get("location", "")).strip()
            teacher = str(course.get("teacher", "")).strip()
            units = str(course.get("units", "")).strip()
            weeks = str(course.get("weeks", "")).strip()
            note = str(course.get("note", "") or course.get("remark", "")).strip()
            parts = [f"{idx}. {start}-{end} {name}".strip()]
            if course_code:
                parts.append(f"课程代码：{course_code}")
            if category:
                parts.append(f"类别：{category}")
            if location:
                parts.append(f"地点：{location}")
            if teacher:
                parts.append(f"老师：{teacher}")
            if units:
                parts.append(f"学分：{units}")
            if weeks:
                parts.append(f"周次：{weeks}")
            if note:
                parts.append(f"备注：{note}")
            line = "\n".join(parts)
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
