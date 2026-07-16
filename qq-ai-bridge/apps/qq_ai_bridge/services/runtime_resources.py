"""Bounded background executors and lightweight runtime metrics."""

from __future__ import annotations

import heapq
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Callable

from apps.qq_ai_bridge.config.settings import (
    RUNTIME_CHAT_MAX_PENDING,
    RUNTIME_CHAT_WORKERS,
    RUNTIME_MEDIA_MAX_PENDING,
    RUNTIME_MEDIA_WORKERS,
    RUNTIME_SCHEDULED_MAX_PENDING,
)


class BoundedExecutor:
    """Thread pool with a hard cap on running plus queued work."""

    def __init__(self, *, name: str, max_workers: int, max_pending: int) -> None:
        self.name = str(name or "runtime")
        self.max_workers = max(1, int(max_workers))
        self.max_pending = max(0, int(max_pending))
        self.capacity = self.max_workers + self.max_pending
        self._slots = threading.BoundedSemaphore(self.capacity)
        self._executor = ThreadPoolExecutor(
            max_workers=self.max_workers,
            thread_name_prefix=self.name,
        )
        self._lock = threading.Lock()
        self._active = 0
        self._pending = 0
        self._submitted = 0
        self._completed = 0
        self._failed = 0
        self._rejected = 0

    def try_submit(
        self,
        fn: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future | None:
        if not self._slots.acquire(blocking=False):
            with self._lock:
                self._rejected += 1
            return None

        with self._lock:
            self._submitted += 1
            self._pending += 1

        def run() -> Any:
            with self._lock:
                self._pending -= 1
                self._active += 1
            failed = False
            try:
                return fn(*args, **kwargs)
            except BaseException:
                failed = True
                raise
            finally:
                with self._lock:
                    self._active -= 1
                    self._completed += 1
                    if failed:
                        self._failed += 1
                self._slots.release()

        try:
            future = self._executor.submit(run)
        except BaseException:
            with self._lock:
                self._pending -= 1
                self._failed += 1
            self._slots.release()
            raise

        def release_cancelled_slot(done: Future) -> None:
            if not done.cancelled():
                return
            with self._lock:
                self._pending -= 1
                self._completed += 1
            self._slots.release()

        future.add_done_callback(release_cancelled_slot)
        return future

    def status(self) -> dict[str, int | str]:
        with self._lock:
            return {
                "name": self.name,
                "max_workers": self.max_workers,
                "max_pending": self.max_pending,
                "capacity": self.capacity,
                "active": self._active,
                "pending": self._pending,
                "submitted": self._submitted,
                "completed": self._completed,
                "failed": self._failed,
                "rejected": self._rejected,
            }

    def shutdown(self, *, wait: bool = True) -> None:
        self._executor.shutdown(wait=wait, cancel_futures=not wait)


class DelayedTaskScheduler:
    """Single-thread delayed scheduler with a bounded heap."""

    def __init__(self, *, name: str, max_pending: int) -> None:
        self.name = str(name or "scheduler")
        self.max_pending = max(1, int(max_pending))
        self._condition = threading.Condition()
        self._tasks: list[tuple[float, int, Callable[..., Any], tuple[Any, ...], dict[str, Any]]] = []
        self._sequence = 0
        self._scheduled = 0
        self._executed = 0
        self._failed = 0
        self._rejected = 0
        self._stopped = False
        self._cancel_pending = False
        self._thread = threading.Thread(target=self._run, name=self.name, daemon=True)
        self._thread.start()

    def schedule(
        self,
        delay_seconds: float,
        fn: Callable[..., Any],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> bool:
        run_at = time.monotonic() + max(0.0, float(delay_seconds))
        with self._condition:
            if self._stopped or len(self._tasks) >= self.max_pending:
                self._rejected += 1
                return False
            self._sequence += 1
            heapq.heappush(self._tasks, (run_at, self._sequence, fn, args, kwargs))
            self._scheduled += 1
            self._condition.notify()
            return True

    def _run(self) -> None:
        while True:
            with self._condition:
                while True:
                    if self._stopped and (self._cancel_pending or not self._tasks):
                        return
                    if not self._tasks:
                        self._condition.wait()
                        continue
                    run_at, _sequence, fn, args, kwargs = self._tasks[0]
                    remaining = run_at - time.monotonic()
                    if remaining > 0:
                        self._condition.wait(timeout=remaining)
                        continue
                    heapq.heappop(self._tasks)
                    break
            failed = False
            try:
                fn(*args, **kwargs)
            except BaseException:
                failed = True
            finally:
                with self._condition:
                    self._executed += 1
                    if failed:
                        self._failed += 1

    def status(self) -> dict[str, int | str]:
        with self._condition:
            return {
                "name": self.name,
                "max_pending": self.max_pending,
                "pending": len(self._tasks),
                "scheduled": self._scheduled,
                "executed": self._executed,
                "failed": self._failed,
                "rejected": self._rejected,
            }

    def shutdown(self, *, wait: bool = True, cancel_pending: bool = False) -> None:
        with self._condition:
            self._stopped = True
            self._cancel_pending = bool(cancel_pending)
            if cancel_pending:
                self._tasks.clear()
            self._condition.notify_all()
        if wait:
            self._thread.join(timeout=2)


_CHAT_EXECUTOR = BoundedExecutor(
    name="qq-chat",
    max_workers=RUNTIME_CHAT_WORKERS,
    max_pending=RUNTIME_CHAT_MAX_PENDING,
)
_MEDIA_EXECUTOR = BoundedExecutor(
    name="qq-media",
    max_workers=RUNTIME_MEDIA_WORKERS,
    max_pending=RUNTIME_MEDIA_MAX_PENDING,
)
_SCHEDULER = DelayedTaskScheduler(
    name="qq-scheduler",
    max_pending=RUNTIME_SCHEDULED_MAX_PENDING,
)


def submit_chat_task(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future | None:
    return _CHAT_EXECUTOR.try_submit(fn, *args, **kwargs)


def submit_media_task(fn: Callable[..., Any], /, *args: Any, **kwargs: Any) -> Future | None:
    return _MEDIA_EXECUTOR.try_submit(fn, *args, **kwargs)


def schedule_task(
    delay_seconds: float,
    fn: Callable[..., Any],
    /,
    *args: Any,
    **kwargs: Any,
) -> bool:
    return _SCHEDULER.schedule(delay_seconds, fn, *args, **kwargs)


def get_runtime_resource_status() -> dict[str, dict[str, int | str]]:
    return {
        "chat": _CHAT_EXECUTOR.status(),
        "media": _MEDIA_EXECUTOR.status(),
        "scheduled": _SCHEDULER.status(),
    }


__all__ = [
    "BoundedExecutor",
    "DelayedTaskScheduler",
    "get_runtime_resource_status",
    "schedule_task",
    "submit_chat_task",
    "submit_media_task",
]
