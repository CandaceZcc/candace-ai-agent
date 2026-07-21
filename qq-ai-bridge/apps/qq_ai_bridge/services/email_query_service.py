"""Deterministic owner command parsing for campus email queries."""

from __future__ import annotations

import re
from datetime import datetime, timedelta

from apps.qq_ai_bridge.config.settings import (
    EMAIL_MAX_MESSAGES_PER_RUN,
    EMAIL_MAX_RANGE_DAYS,
)
from apps.qq_ai_bridge.services.email_models import EmailCommand, EmailQuery
from apps.qq_ai_bridge.services.time_utils import LOCAL_TIMEZONE, get_now_local

_EMAIL_COMMAND_RE = re.compile(r"^\s*邮件(?:\s+(.*?))?\s*$")
_RECENT_RE = re.compile(r"^最近\s+(\d+)\s+天$")


def parse_email_command(
    text: str,
    *,
    now: datetime | None = None,
    max_range_days: int = EMAIL_MAX_RANGE_DAYS,
    limit: int = EMAIL_MAX_MESSAGES_PER_RUN,
) -> EmailCommand:
    match = _EMAIL_COMMAND_RE.fullmatch(str(text or ""))
    if not match:
        return EmailCommand("no_match")

    subcommand = str(match.group(1) or "帮助").strip()
    if subcommand == "状态":
        return EmailCommand("status")
    if subcommand == "帮助":
        return EmailCommand("help")

    current = now or get_now_local()
    if current.tzinfo is None:
        current = current.replace(tzinfo=LOCAL_TIMEZONE)
    today = current.astimezone(LOCAL_TIMEZONE).date()

    if subcommand == "今天":
        return _query_command(today, today, limit, "今天")
    if subcommand == "昨天":
        yesterday = today - timedelta(days=1)
        return _query_command(yesterday, yesterday, limit, "昨天")
    if subcommand == "本周":
        monday = today - timedelta(days=today.weekday())
        return _query_command(monday, today, limit, "本周")
    if subcommand == "上周":
        this_monday = today - timedelta(days=today.weekday())
        last_monday = this_monday - timedelta(days=7)
        return _query_command(last_monday, this_monday - timedelta(days=1), limit, "上周")

    recent_match = _RECENT_RE.fullmatch(subcommand)
    if recent_match:
        days = int(recent_match.group(1))
        if 1 <= days <= max(1, int(max_range_days)):
            start = today - timedelta(days=days - 1)
            return _query_command(start, today, limit, f"最近 {days} 天")
    return EmailCommand("invalid")


def _query_command(start_date, end_date, limit: int, label: str) -> EmailCommand:
    return EmailCommand(
        "query",
        query=EmailQuery(start_date=start_date, end_date=end_date, limit=max(1, int(limit))),
        period_label=label,
    )


__all__ = ["parse_email_command"]
