"""Reminder parsing, intent detection, and formatting helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from apps.qq_ai_bridge.services.time_utils import get_now_local, get_tomorrow_local, get_weekday_cn


HELP_TEXT = """提醒帮助：
1. 提醒我明天下午3点交作业
2. 10分钟后提醒我去洗衣服
3. 今晚11点提醒我背单词
4. 后天早上8点提醒我上课
5. 明天提醒我做作业
6. 明天提醒：1. 学习dcn 2. 做os作业
7. 提醒列表
8. 下一个提醒是什么
9. 最近完成的提醒"""

LIST_COMMANDS = {"提醒列表", "我的提醒", "查看提醒", "提醒清单"}
CLEAR_COMMANDS = {"清空提醒", "删除所有提醒", "清空所有提醒"}
HELP_COMMANDS = {"提醒帮助", "帮助提醒", "reminderhelp"}
DONE_QUERY_COMMANDS = {"最近完成的提醒", "已完成提醒"}
NEXT_QUERY_COMMANDS = {"下一个提醒是什么", "下个提醒是什么", "还有什么提醒", "还有哪些提醒", "下一条提醒是什么"}
DEFAULT_TOMORROW_HOUR = 9
DEFAULT_TOMORROW_MINUTE = 0
MULTI_ITEM_OFFSET_MINUTES = 5


@dataclass
class ReminderParseResult:
    trigger_at: datetime
    text: str
    note: str = ""


@dataclass
class ReminderIntent:
    kind: str
    reason: str


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "")).strip()


def detect_reminder_intent(text: str) -> ReminderIntent | None:
    raw = str(text or "").strip()
    normalized = normalize_text(raw)
    if not normalized:
        return None

    if normalized in HELP_COMMANDS:
        return ReminderIntent(kind="help", reason="help_command")
    if normalized in LIST_COMMANDS:
        return ReminderIntent(kind="list_pending", reason="query_list")
    if normalized in DONE_QUERY_COMMANDS:
        return ReminderIntent(kind="recent_done", reason="query_done_history")
    if normalized in NEXT_QUERY_COMMANDS:
        return ReminderIntent(kind="next_pending", reason="query_next_reminder")
    if parse_delete_command(raw) is not None:
        return ReminderIntent(kind="delete", reason="delete_command")
    if normalized in CLEAR_COMMANDS:
        return ReminderIntent(kind="clear", reason="clear_command")
    if _is_tomorrow_overview_query(normalized):
        return ReminderIntent(kind="tomorrow_overview", reason="query_tomorrow_schedule")
    if _is_tomorrow_schedule_query(normalized):
        return ReminderIntent(kind="tomorrow_schedule", reason="query_tomorrow_schedule")
    if _is_tomorrow_reminder_query(normalized):
        return ReminderIntent(kind="tomorrow_reminders", reason="query_tomorrow_reminders")
    if _is_add_command(raw):
        return ReminderIntent(kind="add", reason="add_reminder")
    return None


def is_reminder_command(text: str) -> bool:
    return detect_reminder_intent(text) is not None


def parse_delete_command(text: str) -> int | None:
    match = re.match(r"^(?:删除|取消)提醒\s*(\d+)$", str(text or "").strip())
    if not match:
        match = re.match(r"^(?:删除|取消)提醒(\d+)$", normalize_text(text))
    return int(match.group(1)) if match else None


def parse_reminder_commands(text: str, now: datetime | None = None) -> list[ReminderParseResult]:
    now = now.astimezone(get_now_local().tzinfo) if now else get_now_local()
    raw = str(text or "").strip()

    relative_result = _parse_relative(raw, now)
    if relative_result:
        return [relative_result]

    absolute_result = _parse_absolute(raw, now)
    if absolute_result:
        return [absolute_result]

    tomorrow_results = _parse_tomorrow_default(raw, now)
    if tomorrow_results:
        return tomorrow_results

    raise ValueError("无法识别时间/内容")


def build_add_success_message(items: list[dict], note: str = "") -> str:
    if len(items) == 1:
        item = items[0]
        parts = [
            f"已添加提醒 [{item.get('id')}]",
            f"时间：{_format_dt(item.get('trigger_at', ''))}",
            f"内容：{item.get('text', '')}",
        ]
    else:
        parts = [f"已添加 {len(items)} 条明天提醒："]
        for item in items:
            parts.append(f"[{item.get('id')}] {_format_dt(item.get('trigger_at', ''))} {item.get('text', '')}")
    if note:
        parts.append(f"说明：{note}")
    return "\n".join(parts)


def build_list_message(items: list[dict]) -> str:
    if not items:
        return "当前没有待触发提醒。"
    lines = ["待触发提醒列表："]
    for item in items:
        lines.append(
            f"[{item.get('id')}] {_format_dt(item.get('trigger_at', ''))}\n"
            f"内容：{item.get('text', '')}\n"
            "状态：待触发"
        )
    return "\n\n".join(lines)


def build_done_list_message(items: list[dict]) -> str:
    if not items:
        return "当前没有最近完成的提醒。"
    lines = ["最近完成的提醒："]
    for idx, item in enumerate(items, start=1):
        fired_at = _format_dt(item.get("fired_at") or item.get("trigger_at", ""))
        lines.append(f"{idx}. [{item.get('id')}] {fired_at} {item.get('text', '')}")
    return "\n".join(lines)


def build_next_pending_message(item: dict | None) -> str:
    if not item:
        return "当前没有待触发提醒。"
    return (
        "下一个提醒：\n"
        f"[{item.get('id')}] {_format_dt(item.get('trigger_at', ''))}\n"
        f"内容：{item.get('text', '')}"
    )


def query_tomorrow_reminders(items: list[dict], now: datetime | None = None) -> dict:
    now_local = now.astimezone(get_now_local().tzinfo) if now else get_now_local()
    tomorrow_date = (now_local + timedelta(days=1)).date()
    matched = []
    for item in items:
        try:
            trigger_at = datetime.fromisoformat(item.get("trigger_at", "")).astimezone(get_now_local().tzinfo)
        except ValueError:
            continue
        if trigger_at.date() == tomorrow_date:
            matched.append((trigger_at, item))
    matched.sort(key=lambda pair: pair[0])
    print(
        f"[REMINDER_QUERY] tomorrow date={tomorrow_date.isoformat()}"
        f" weekday={get_weekday_cn(tomorrow_date)}"
        f" pending_count={len(matched)}"
    )
    return {
        "date": tomorrow_date.isoformat(),
        "weekday_cn": get_weekday_cn(tomorrow_date),
        "items": matched,
    }


def build_tomorrow_reminders_reply(items: list[dict], now: datetime | None = None) -> str:
    query = query_tomorrow_reminders(items, now=now)
    matched = query["items"]
    if not matched:
        return "明天没有待触发提醒。"
    lines = ["明天待提醒："]
    for idx, (trigger_at, item) in enumerate(matched, start=1):
        lines.append(f"{idx}. {trigger_at.strftime('%H:%M')} {item.get('text', '')}")
    return "\n".join(lines)


def _is_add_command(text: str) -> bool:
    normalized = normalize_text(text)
    return any(
        re.match(pattern, normalized)
        for pattern in (
            r"^\d+(分钟|小时)后提醒我.+$",
            r"^(今天|明天|后天|今晚).+提醒我.+$",
            r"^提醒我(今天|明天|后天|今晚).+$",
            r"^(明天提醒我|明天提醒|明天记得|明天要做).+$",
        )
    )


def _is_tomorrow_overview_query(text: str) -> bool:
    return any(
        token in text
        for token in (
            "明天有什么课或者提醒",
            "明天有什么课和提醒",
            "明天有课和提醒吗",
            "明天有提醒和课吗",
            "明天课和提醒",
            "明天课程和提醒",
        )
    )


def _is_tomorrow_schedule_query(text: str) -> bool:
    return (
        "明天" in text
        and any(token in text for token in ("课", "课程"))
        and "提醒" not in text
    )


def _is_tomorrow_reminder_query(text: str) -> bool:
    return "明天" in text and "提醒" in text and not any(token in text for token in ("课", "课程"))


def _parse_relative(text: str, now: datetime) -> ReminderParseResult | None:
    normalized = normalize_text(text)
    match = re.match(r"^(?P<num>\d+)分钟后提醒我(?P<content>.+)$", normalized)
    if match:
        print("[REMINDER_PARSE] matched rule=relative_minutes")
        return ReminderParseResult(now + timedelta(minutes=int(match.group("num"))), match.group("content").strip())

    match = re.match(r"^(?P<num>\d+)小时后提醒我(?P<content>.+)$", normalized)
    if match:
        print("[REMINDER_PARSE] matched rule=relative_hours")
        return ReminderParseResult(now + timedelta(hours=int(match.group("num"))), match.group("content").strip())
    return None


def _parse_absolute(text: str, now: datetime) -> ReminderParseResult | None:
    normalized = normalize_text(text)
    patterns = [
        ("absolute_day_first", r"^(?P<day>今天|明天|后天|今晚)(?P<period>凌晨|早上|上午|中午|下午|晚上)?(?P<hour>\d{1,2})(?P<suffix>点半|点\d{0,2}|[:：]\d{1,2})?提醒我(?P<content>.+)$"),
        ("absolute_remind_me_first", r"^提醒我(?P<day>今天|明天|后天|今晚)(?P<period>凌晨|早上|上午|中午|下午|晚上)?(?P<hour>\d{1,2})(?P<suffix>点半|点\d{0,2}|[:：]\d{1,2})?(?P<content>.+)$"),
    ]
    for rule_name, pattern in patterns:
        match = re.match(pattern, normalized)
        if not match:
            continue
        print(f"[REMINDER_PARSE] matched rule={rule_name}")
        content = match.group("content").strip()
        trigger_at, note = _resolve_day_time(
            now=now,
            day_word=match.group("day"),
            period=match.group("period") or "",
            hour=int(match.group("hour")),
            minute=_parse_minute_suffix(match.group("suffix") or ""),
        )
        return ReminderParseResult(trigger_at, content, note)
    return None


def _parse_tomorrow_default(text: str, now: datetime) -> list[ReminderParseResult]:
    raw = str(text or "").strip()
    prefix_patterns = [
        ("tomorrow_remind_me_default", r"^明天提醒我(?P<body>.+)$"),
        ("tomorrow_remind_default", r"^明天提醒[:：]?\s*(?P<body>.+)$"),
        ("tomorrow_remember_default", r"^明天记得(?P<body>.+)$"),
        ("tomorrow_todo_default", r"^明天要做[:：]?\s*(?P<body>.+)$"),
    ]
    for rule_name, pattern in prefix_patterns:
        match = re.match(pattern, raw)
        if not match:
            continue
        body = str(match.group("body") or "").strip()
        if rule_name == "tomorrow_todo_default" and re.match(r"^明天要做[^:：]", raw):
            body = f"做{body}".strip()
        items = _split_tomorrow_items(body)
        if not items:
            break
        print(f"[REMINDER_PARSE] matched rule={rule_name}")
        print(f"[REMINDER_PARSE] split count={len(items)}")
        base_time = _build_tomorrow_default_time(now)
        return [
            ReminderParseResult(
                trigger_at=base_time + timedelta(minutes=MULTI_ITEM_OFFSET_MINUTES * idx),
                text=item_text,
                note="未指定具体时间，已默认设置为明天 09:00。" if idx == 0 else "",
            )
            for idx, item_text in enumerate(items)
        ]
    return []


def _split_tomorrow_items(body: str) -> list[str]:
    numbered = re.findall(r"(?:^|[;；\s])\d+[.、]\s*([^;；]+?)(?=(?:[;；\s]\d+[.、])|$)", body)
    if numbered:
        return [item.strip(" \t;；、，,") for item in numbered if item.strip(" \t;；、，,")]
    cleaned = re.sub(r"^\s*[:：]\s*", "", body).strip()
    if any(separator in cleaned for separator in ("；", ";", "、")):
        return [part.strip(" \t,，") for part in re.split(r"[；;、]+", cleaned) if part.strip(" \t,，")]
    return [cleaned] if cleaned else []


def _build_tomorrow_default_time(now: datetime) -> datetime:
    tomorrow_date = (now + timedelta(days=1)).date()
    return datetime(
        year=tomorrow_date.year,
        month=tomorrow_date.month,
        day=tomorrow_date.day,
        hour=DEFAULT_TOMORROW_HOUR,
        minute=DEFAULT_TOMORROW_MINUTE,
        tzinfo=now.tzinfo,
    )


def _resolve_day_time(now: datetime, day_word: str, period: str, hour: int, minute: int) -> tuple[datetime, str]:
    base_date = now.date()
    if day_word == "明天":
        base_date += timedelta(days=1)
    elif day_word == "后天":
        base_date += timedelta(days=2)
    elif day_word == "今晚":
        period = period or "晚上"
    normalized_hour = _normalize_hour(hour, period)
    trigger_at = datetime(base_date.year, base_date.month, base_date.day, normalized_hour, minute, tzinfo=now.tzinfo)
    note = ""
    if trigger_at <= now:
        trigger_at += timedelta(days=1)
        note = "原时间已过去，已自动顺延到下一天。"
    return trigger_at, note


def _normalize_hour(hour: int, period: str) -> int:
    if period in {"下午", "晚上"} and 1 <= hour <= 11:
        return hour + 12
    if period == "中午" and 1 <= hour <= 10:
        return hour + 12
    if period == "凌晨" and hour == 12:
        return 0
    return hour


def _parse_minute_suffix(suffix: str) -> int:
    if not suffix or suffix == "点":
        return 0
    if suffix == "点半":
        return 30
    if suffix.startswith("点"):
        minute_text = suffix[1:]
        return int(minute_text) if minute_text else 0
    if suffix.startswith((":", "：")):
        return int(suffix[1:])
    raise ValueError("无法识别时间/内容")


def _format_dt(value: str) -> str:
    try:
        dt = datetime.fromisoformat(value).astimezone(get_now_local().tzinfo)
    except ValueError:
        return value
    return dt.strftime("%Y-%m-%d %H:%M")
