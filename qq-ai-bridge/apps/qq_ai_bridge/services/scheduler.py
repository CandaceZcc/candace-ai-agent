"""Background scheduler for private QQ reminders."""

from __future__ import annotations

import threading
import time
import traceback
from datetime import datetime, timedelta
from math import ceil

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import (
    BARRAGE_6657_STARTUP_SYNC_PAGES,
    BARRAGE_6657_SYNC_TIME,
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
    VOCAT_DAILY_BROADCAST_TO_DEVICE,
)
from apps.qq_ai_bridge.logging.bridge_log import log_change, log_debug, log_warn
from apps.qq_ai_bridge.services.barrage_6657_service import sync_6657_barrages_safely
from apps.qq_ai_bridge.services.reminder_store import ReminderStore, SchedulerStateStore
from apps.qq_ai_bridge.services.schedule_service import (
    build_tomorrow_schedule_message,
    ensure_schedule_file,
)
from apps.qq_ai_bridge.services.time_utils import get_now_local
from apps.qq_ai_bridge.services.trace_store import (
    add_trace_step,
    finish_trace,
    new_trace_id,
    start_trace,
    trace_prefix,
)
from apps.qq_ai_bridge.services.vocat_command_queue import enqueue_vocat_tts

_START_LOCK = threading.Lock()
_STARTED = False
_STARTED_AT: datetime | None = None
_6657_DAILY_SYNC_LOCK = threading.Lock()
_6657_DAILY_SYNC_IN_FLIGHT = False
_6657_SYNC_OPERATION_LOCK = threading.Lock()

REMINDER_STORE = ReminderStore(REMINDERS_PATH)
STATE_STORE = SchedulerStateStore(SCHEDULER_STATE_PATH)


# start_scheduler：启动后台调度器
def start_scheduler() -> None:
    """Start the scheduler thread once."""
    global _STARTED, _STARTED_AT
    with _START_LOCK:
        if _STARTED:
            return
        _STARTED = True
        _STARTED_AT = get_now_local()
        ensure_schedule_file(SCHEDULE_PATH)
        sync_worker = threading.Thread(
            target=_run_6657_startup_sync,
            name="6657-startup-sync",
            daemon=True,
        )
        sync_worker.start()
        worker = threading.Thread(target=_scheduler_loop, name="qq-reminder-scheduler", daemon=True)
        worker.start()
        print(
            f"[SCHEDULER] started tick_seconds={SCHEDULER_TICK_SECONDS}"
            f" owner_qq={OWNER_QQ}"
            f" sleep_time={SLEEP_REMINDER_TIME}"
            f" schedule_time={TOMORROW_SCHEDULE_TIME}"
        )


# _scheduler_loop：循环处理
def _scheduler_loop() -> None:
    while True:
        now = get_now_local()
        log_debug("SCHEDULER", "tick now=%s", now.isoformat())
        try:
            next_reminder_wait = _fire_due_reminders(now)
            _run_daily_jobs(now)
            sleep_seconds = _compute_sleep_seconds(now, next_reminder_wait)
        except Exception:
            log_warn("SCHEDULER", "loop error")
            traceback.print_exc()
            sleep_seconds = SCHEDULER_TICK_SECONDS
        log_debug("SCHEDULER", "sleep seconds=%s", sleep_seconds)
        time.sleep(sleep_seconds)


# _fire_due_reminders：相关逻辑处理
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
                _queue_vocat_daily_broadcast(f"提醒你：{item['text']}", source="reminder")
            print(f"[REMINDER] sent id={reminder_id} ret={result}")
        except Exception:
            print(f"[REMINDER] send failed id={reminder_id}")
            traceback.print_exc()
    return next_wait


# _run_daily_jobs：运行每日任务
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
    _schedule_6657_daily_sync(now)


def _run_6657_startup_sync() -> None:
    with _6657_SYNC_OPERATION_LOCK:
        sync_6657_barrages_safely(
            max_pages=BARRAGE_6657_STARTUP_SYNC_PAGES,
            log=print,
        )


def _schedule_6657_daily_sync(now: datetime) -> None:
    global _6657_DAILY_SYNC_IN_FLIGHT
    scheduled_at = _resolve_daily_job_time(now, BARRAGE_6657_SYNC_TIME, 0)
    token = _build_daily_token("barrage_6657_sync", now, 0)
    if now < scheduled_at or STATE_STORE.was_daily_sent("barrage_6657_sync", token):
        return
    with _6657_DAILY_SYNC_LOCK:
        if _6657_DAILY_SYNC_IN_FLIGHT:
            return
        _6657_DAILY_SYNC_IN_FLIGHT = True
    worker = threading.Thread(
        target=_run_6657_daily_sync_worker,
        args=(now, token),
        name="6657-daily-sync",
        daemon=True,
    )
    worker.start()


def _run_6657_daily_sync_worker(now: datetime, token: str) -> None:
    global _6657_DAILY_SYNC_IN_FLIGHT
    try:
        _execute_6657_daily_sync(now, token)
    finally:
        with _6657_DAILY_SYNC_LOCK:
            _6657_DAILY_SYNC_IN_FLIGHT = False


def _execute_6657_daily_sync(now: datetime, token: str) -> None:
    with _6657_SYNC_OPERATION_LOCK:
        result = sync_6657_barrages_safely(log=print)
    if result.get("ok"):
        STATE_STORE.mark_daily_sent("barrage_6657_sync", token, now)
        print(f"[DAILY] barrage_6657_sync fired date={token}")
    else:
        print(f"[DAILY] barrage_6657_sync failed date={token} error={result.get('error')}")


# _run_daily_job：运行每日任务
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
        log_change(
            "DAILY",
            f"daily_skipped:{task_key}",
            token,
            "skipped already sent date=%s task=%s",
            token,
            task_key,
        )
        return
    try:
        result = send_private_msg(OWNER_QQ, schedule_text, quiet=True)
        if result.get("ok"):
            STATE_STORE.mark_daily_sent(task_key, token, now)
            _queue_vocat_daily_broadcast(schedule_text, source=task_key)
            print(f"{success_log_prefix} fired date={token}")
        else:
            print(f"[DAILY] send failed task={task_key} token={token} ret={result}")
    except Exception:
        print(f"[DAILY] send failed task={task_key} token={token}")
        traceback.print_exc()


# _resolve_daily_job_time：解析每日任务时间
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


# _build_daily_token：构建每日令牌
def _build_daily_token(task_key: str, now: datetime, test_delay_minutes: int) -> str:
    if test_delay_minutes > 0:
        return f"{now.date().isoformat()}-test-{task_key}-{test_delay_minutes}m"
    return now.date().isoformat()


# _compute_sleep_seconds：睡眠秒数处理
def _compute_sleep_seconds(now: datetime, next_reminder_wait: int | None) -> int:
    waits = [SCHEDULER_TICK_SECONDS]
    if next_reminder_wait is not None:
        waits.append(next_reminder_wait)

    for task_key, hhmm, delay in (
        ("sleep_reminder", SLEEP_REMINDER_TIME, SLEEP_REMINDER_TEST_DELAY_MINUTES),
        ("tomorrow_schedule", TOMORROW_SCHEDULE_TIME, TOMORROW_SCHEDULE_TEST_DELAY_MINUTES),
        ("barrage_6657_sync", BARRAGE_6657_SYNC_TIME, 0),
    ):
        scheduled_at = _resolve_daily_job_time(now, hhmm, delay)
        token = _build_daily_token(task_key, now, delay)
        if STATE_STORE.was_daily_sent(task_key, token):
            continue
        if scheduled_at > now:
            waits.append(max(1, ceil((scheduled_at - now).total_seconds())))

    return max(1, min(waits))


def _queue_vocat_daily_broadcast(text: str, *, source: str) -> None:
    if not VOCAT_DAILY_BROADCAST_TO_DEVICE:
        return
    trace_id = new_trace_id({})
    start_trace(trace_id, source="scheduler", input_text=text[:180])
    add_trace_step(trace_id, "scheduler", source=source)
    result = enqueue_vocat_tts(text, source=f"scheduler_{source}")
    if result.get("ok"):
        add_trace_step(trace_id, "send", target="vocat_queue", command_id=result.get("command_id"))
        print(f"{trace_prefix(trace_id)}[VOCAT] queued scheduler broadcast command_id={result.get('command_id')} source={source}")
        finish_trace(trace_id, result=result.get("command_id"), status="ok", source="scheduler")
    else:
        print(f"{trace_prefix(trace_id)}[VOCAT] failed to queue scheduler broadcast source={source} ret={result}")
        finish_trace(trace_id, result=result, status="error", source="scheduler")
