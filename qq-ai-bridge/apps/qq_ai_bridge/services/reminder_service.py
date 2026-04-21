"""Reminder parsing and reply helpers."""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import Any

from apps.qq_ai_bridge.services.time_utils import get_now_local

HELP_COMMANDS = {"提醒帮助", "提醒 help", "reminder help", "help 提醒"}
LIST_COMMANDS = {"提醒列表", "我的提醒", "查看提醒", "提醒 list", "list reminder"}
CLEAR_COMMANDS = {"清空提醒", "删除全部提醒", "提醒 clear", "clear reminder"}
HELP_TEXT = (
    "提醒用法示例：\n"
    "1. 提醒我明天早上9点开会\n"
    "2. 提醒列表\n"
    "3. 删除提醒 3\n"
    "4. 明天有什么提醒"
)

_DELETE_PATTERN = re.compile(r"(?:删除提醒|取消提醒|提醒删除)\s*(\d+)", re.IGNORECASE)
_RELATIVE_DAY_PATTERN = re.compile(r"(今天|明天|后天)")
_TIME_PATTERN = re.compile(
    r"(?:(早上|上午|中午|下午|晚上))?\s*(\d{1,2})[:点时]?(\d{1,2})?\s*分?",
    re.IGNORECASE,
)


@dataclass
class ReminderIntent:
    kind: str
    reason: str


@dataclass
class ParsedReminderCommand:
    text: str
    trigger_at: dt.datetime
    note: str = ""


class ReminderService:
    """Manages the parsing, creation, and retrieval of reminders."""

    def __init__(self, store):
        self.store = store

    def process_add_reminder(self, user_id: int, reminder_text: str, trigger_at: dt.datetime) -> dict[str, Any]:
        try:
            return self.store.add_reminder(user_id, trigger_at, reminder_text)
        except KeyError as e:
            return {"status": "error", "message": f"创建提醒失败：缺少必填字段 {e}"}

    def delete_reminder(self, user_id: int, reminder_id: int) -> bool:
        return self.store.cancel_reminder(reminder_id, user_id=user_id) is not None

    def list_reminders(self, user_id: int) -> list[dict[str, Any]]:
        try:
            return self.store.list_pending(user_id)
        except Exception as e:
            print(f"[REMINDER] Failed to list reminders: {e}")
            return []


def normalize_text(text: str) -> str:
    return re.sub(r"\s+", "", str(text or "").strip())


def detect_reminder_intent(text: str) -> ReminderIntent | None:
    normalized = normalize_text(text)
    if not normalized:
        return None
    if normalized in HELP_COMMANDS:
        return ReminderIntent(kind="help", reason="help_command")
    if normalized in LIST_COMMANDS or "提醒列表" in normalized or "我的提醒" in normalized:
        return ReminderIntent(kind="list_pending", reason="list_command")
    if "最近提醒" in normalized or "已完成提醒" in normalized:
        return ReminderIntent(kind="recent_done", reason="recent_done_query")
    if "下一个提醒" in normalized or "最近一个提醒" in normalized:
        return ReminderIntent(kind="next_pending", reason="next_pending_query")
    if "明天有什么提醒" in normalized or "明日提醒" in normalized:
        return ReminderIntent(kind="tomorrow_reminders", reason="tomorrow_reminders_query")
    if parse_delete_command(text) is not None:
        return ReminderIntent(kind="delete", reason="delete_command")
    if normalized in CLEAR_COMMANDS:
        return ReminderIntent(kind="clear", reason="clear_command")
    if "提醒我" in normalized or normalized.startswith("提醒"):
        return ReminderIntent(kind="add", reason="add_command")
    return None


def is_reminder_command(text: str) -> bool:
    return detect_reminder_intent(text) is not None


def parse_delete_command(text: str) -> int | None:
    match = _DELETE_PATTERN.search(str(text or ""))
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def _resolve_relative_date(text: str, now: dt.datetime) -> dt.date:
    match = _RELATIVE_DAY_PATTERN.search(text)
    if not match:
        return now.date()
    keyword = match.group(1)
    offset = {"今天": 0, "明天": 1, "后天": 2}.get(keyword, 0)
    return (now + dt.timedelta(days=offset)).date()


def _resolve_hour(period: str | None, hour: int) -> int:
    if period in {"下午", "晚上"} and hour < 12:
        return hour + 12
    if period == "中午" and hour < 11:
        return hour + 12
    return hour


def parse_reminder_commands(text: str, now: dt.datetime | None = None) -> list[ParsedReminderCommand]:
    now = now or get_now_local()
    raw = str(text or "").strip()
    time_match = _TIME_PATTERN.search(raw)
    if not time_match:
        raise ValueError("还没识别到提醒时间，可以试试“提醒我明天早上9点开会”。")

    period = time_match.group(1)
    hour = int(time_match.group(2))
    minute = int(time_match.group(3) or 0)
    hour = _resolve_hour(period, hour)
    target_date = _resolve_relative_date(raw, now)
    trigger_at = dt.datetime.combine(
        target_date,
        dt.time(hour=hour, minute=minute, tzinfo=now.tzinfo),
    )
    if trigger_at <= now:
        trigger_at += dt.timedelta(days=1)

    reminder_text = raw
    for token in ("提醒我", "提醒一下我", "提醒", "闹钟"):
        reminder_text = reminder_text.replace(token, "", 1).strip()
    reminder_text = _TIME_PATTERN.sub("", reminder_text, count=1).strip(" ，,。")
    reminder_text = _RELATIVE_DAY_PATTERN.sub("", reminder_text, count=1).strip(" ，,。")
    if not reminder_text:
        reminder_text = "待办事项"

    return [ParsedReminderCommand(text=reminder_text, trigger_at=trigger_at)]


def _format_single_reminder(item: dict[str, Any]) -> str:
    trigger_at = str(item.get("trigger_at", ""))
    text = str(item.get("text", "")).strip()
    return f"[{item.get('id')}] {trigger_at} - {text}"


def build_list_message(items: list[dict[str, Any]]) -> str:
    if not items:
        return "你现在没有待触发的提醒。"
    lines = ["你当前的提醒："]
    lines.extend(_format_single_reminder(item) for item in items)
    return "\n".join(lines)


def build_done_list_message(items: list[dict[str, Any]]) -> str:
    if not items:
        return "最近没有已完成提醒。"
    lines = ["最近完成的提醒："]
    lines.extend(_format_single_reminder(item) for item in items)
    return "\n".join(lines)


def build_next_pending_message(item: dict[str, Any] | None) -> str:
    if not item:
        return "目前没有待触发提醒。"
    return f"最近一个提醒是：{_format_single_reminder(item)}"


def build_add_success_message(items: list[dict[str, Any]], note: str = "") -> str:
    if not items:
        return "提醒创建失败。"
    lines = ["已经帮你记下来了："]
    lines.extend(_format_single_reminder(item) for item in items)
    if note:
        lines.append(note)
    return "\n".join(lines)


def query_tomorrow_reminders(pending_items: list[dict[str, Any]], now: dt.datetime | None = None) -> dict[str, Any]:
    now = now or get_now_local()
    tomorrow = (now + dt.timedelta(days=1)).date()
    tomorrow_items = []
    for item in pending_items:
        trigger_raw = str(item.get("trigger_at", "")).strip()
        if not trigger_raw:
            continue
        try:
            trigger_dt = dt.datetime.fromisoformat(trigger_raw)
        except ValueError:
            continue
        if trigger_dt.date() == tomorrow:
            tomorrow_items.append(item)
    return {
        "date": tomorrow.isoformat(),
        "weekday_cn": "明天",
        "items": sorted(tomorrow_items, key=lambda item: item.get("trigger_at", "")),
    }


def build_tomorrow_reminders_reply(pending_items: list[dict[str, Any]], now: dt.datetime | None = None) -> str:
    result = query_tomorrow_reminders(pending_items, now=now)
    if not result["items"]:
        return "明天没有待触发提醒。"
    lines = ["明天的提醒有："]
    lines.extend(_format_single_reminder(item) for item in result["items"])
    return "\n".join(lines)
