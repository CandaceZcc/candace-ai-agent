"""Background scheduler for private QQ reminders."""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timedelta
from math import ceil

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import (
    OWNER_QQ,
    REMINDERS_PATH,
    SCHEDULE_PATH,
    SCHEDULER_STATE_PATH,
    SCHEDULER_TICK_SECONDS,
    SLEEP_REMINDER_TEST_DELAY_MINUTES,
    SLEEP_REMINDER_TEXT,
    SLEEP_REMINDER_TIME,
    TOMORROW_SCHEDULE_TEST_DELAY_MINUTES,
    TOMORROW_SCHEDULE_TIME,
)
from apps.qq_ai_bridge.services.reminder_store import ReminderStore, SchedulerStateStore
from apps.qq_ai_bridge.services.schedule_service import build_tomorrow_schedule_message, ensure_schedule_file
from apps.qq_ai_bridge.services.time_utils import get_now_local


_START_LOCK = threading.Lock()
_STARTED = False
_STARTED_AT: datetime | None = None

REMINDER_STORE = ReminderStore(REMINDERS_PATH)
STATE_STORE = SchedulerStateStore(SCHEDULER_STATE_PATH)


def start_scheduler() -> None:
    """Start the scheduler thread once."""
    global _STARTED, _STARTED_AT
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True
        _STARTED_AT = get_now_local()
        ensure_schedule_file(SCHEDULE_PATH)
        worker = threading.Thread(target=_scheduler_loop, name="qq-reminder-scheduler", daemon=True)
        worker.start()
        print(
            f"[SCHEDULER] started tick_seconds={SCHEDULER_TICK_SECONDS}"
            f" owner_qq={OWNER_QQ}"
            f" sleep_time={SLEEP_REMINDER_TIME}"
            f" schedule_time={TOMORROW_SCHEDULE_TIME}"
        )


def _scheduler_loop() -> None:
    while True:
        now = get_now_local()
        print(f"[SCHEDULER] tick now={now.isoformat()}")
        try:
            next_reminder_wait = _fire_due_reminders(now)
            _run_daily_jobs(now)
            sleep_seconds = _compute_sleep_seconds(now, next_reminder_wait)
        except Exception:
            print("[SCHEDULER] loop error")
            traceback.print_exc()
            sleep_seconds = SCHEDULER_TICK_SECONDS
        print(f"[SCHEDULER] sleep seconds={sleep_seconds}")
        time.sleep(sleep_seconds)


def _fire_due_reminders(now: datetime) -> int | None:
    reminders = REMINDER_STORE.list_pending()
    next_wait: int | None = None
    for item in reminders:
        try:
            trigger_at = datetime.fromisoformat(item["trigger_at"])
        except Exception:
            print(f"[REMINDER] invalid trigger_at id={item.get('id')} value={item.get('trigger_at')!r}")
            traceback.print_exc()
            continue
        if trigger_at > now:
            wait_seconds = max(1, ceil((trigger_at - now).total_seconds()))
            next_wait = wait_seconds if next_wait is None else min(next_wait, wait_seconds)
            continue
        reminder_id = int(item["id"])
        print(f"[REMINDER] firing id={reminder_id}")
        try:
            result = send_private_msg(item["user_id"], f"提醒你：{item['text']}", quiet=True)
            if result.get("ok"):
                REMINDER_STORE.mark_fired(reminder_id, now)
            print(f"[REMINDER] sent id={reminder_id} ret={result}")
        except Exception:
            print(f"[REMINDER] send failed id={reminder_id}")
            traceback.print_exc()
    return next_wait


def _run_daily_jobs(now: datetime) -> None:
    _run_daily_job(
        now=now,
        task_key="sleep_reminder",
        schedule_text=SLEEP_REMINDER_TEXT,
        scheduled_at=_resolve_daily_job_time(now, SLEEP_REMINDER_TIME, SLEEP_REMINDER_TEST_DELAY_MINUTES),
        token=_build_daily_token("sleep_reminder", now, SLEEP_REMINDER_TEST_DELAY_MINUTES),
        success_log_prefix="[DAILY] sleep_reminder",
    )
    _run_daily_job(
        now=now,
        task_key="tomorrow_schedule",
        schedule_text=build_tomorrow_schedule_message(SCHEDULE_PATH, now=now),
        scheduled_at=_resolve_daily_job_time(now, TOMORROW_SCHEDULE_TIME, TOMORROW_SCHEDULE_TEST_DELAY_MINUTES),
        token=_build_daily_token("tomorrow_schedule", now, TOMORROW_SCHEDULE_TEST_DELAY_MINUTES),
        success_log_prefix="[DAILY] tomorrow_schedule",
    )


def _run_daily_job(
    now: datetime,
    task_key: str,
    schedule_text: str,
    scheduled_at: datetime,
    token: str,
    success_log_prefix: str,
) -> None:
    if now < scheduled_at:
        return
    if STATE_STORE.was_daily_sent(task_key, token):
        print(f"[DAILY] skipped already sent date={token} task={task_key}")
        return
    try:
        result = send_private_msg(OWNER_QQ, schedule_text, quiet=True)
        if result.get("ok"):
            STATE_STORE.mark_daily_sent(task_key, token, now)
            print(f"{success_log_prefix} fired date={token}")
        else:
            print(f"[DAILY] send failed task={task_key} token={token} ret={result}")
    except Exception:
        print(f"[DAILY] send failed task={task_key} token={token}")
        traceback.print_exc()


def _resolve_daily_job_time(now: datetime, hhmm: str, test_delay_minutes: int) -> datetime:
    if test_delay_minutes > 0 and _STARTED_AT is not None:
        return _STARTED_AT + timedelta(minutes=test_delay_minutes)

    try:
        hour_text, minute_text = hhmm.split(":", 1)
        hour = int(hour_text)
        minute = int(minute_text)
    except Exception:
        print(f"[SCHEDULER] invalid daily time={hhmm!r}, fallback=00:00")
        hour = 0
        minute = 0
    return now.replace(hour=hour, minute=minute, second=0, microsecond=0)


def _build_daily_token(task_key: str, now: datetime, test_delay_minutes: int) -> str:
    if test_delay_minutes > 0:
        return f"{now.date().isoformat()}-test-{task_key}-{test_delay_minutes}m"
    return now.date().isoformat()


def _compute_sleep_seconds(now: datetime, next_reminder_wait: int | None) -> int:
    waits = [SCHEDULER_TICK_SECONDS]
    if next_reminder_wait is not None:
        waits.append(next_reminder_wait)

    for task_key, hhmm, delay in (
        ("sleep_reminder", SLEEP_REMINDER_TIME, SLEEP_REMINDER_TEST_DELAY_MINUTES),
        ("tomorrow_schedule", TOMORROW_SCHEDULE_TIME, TOMORROW_SCHEDULE_TEST_DELAY_MINUTES),
    ):
        scheduled_at = _resolve_daily_job_time(now, hhmm, delay)
        token = _build_daily_token(task_key, now, delay)
        if STATE_STORE.was_daily_sent(task_key, token):
            continue
        if scheduled_at > now:
            waits.append(max(1, ceil((scheduled_at - now).total_seconds())))

    return max(1, min(waits))
