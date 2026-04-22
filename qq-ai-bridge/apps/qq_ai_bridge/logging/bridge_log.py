"""Lightweight logging helpers that let us silence heartbeat/noise lines.

Environment variable ``BRIDGE_LOG_LEVEL`` controls verbosity:
- ``debug``  — print everything, including scheduler ticks and skill skips
- ``info``   — (default) print events (message in/out, reply, errors) but
                drop repeating heartbeats/tick loops
- ``quiet``  — only warnings/errors + first-time/changed state

Usage:

    from apps.qq_ai_bridge.logging.bridge_log import log_debug, log_event,
        log_change, log_warn

    log_event("WEBHOOK", "recv private user_id=%s", user_id)       # always prints
    log_debug("SCHEDULER", "tick now=%s", now)                     # only if debug
    log_change("STORE", ("reminders", count, pending), ...)        # only when key changed
"""

from __future__ import annotations

import os
import sys
from typing import Any

_LEVEL = (os.getenv("BRIDGE_LOG_LEVEL") or "info").strip().lower()
if _LEVEL not in {"debug", "info", "quiet"}:
    _LEVEL = "info"

_LEVEL_RANK = {"debug": 0, "info": 1, "quiet": 2}
_CURRENT_RANK = _LEVEL_RANK[_LEVEL]


def current_level() -> str:
    """Return the effective bridge log level."""
    return _LEVEL


def _emit(prefix: str, message: str) -> None:
    sys.stdout.write(f"[{prefix}] {message}\n")
    sys.stdout.flush()


def _fmt(message: str, args: tuple[Any, ...]) -> str:
    if not args:
        return message
    try:
        return message % args
    except Exception:
        return message + " " + " ".join(repr(a) for a in args)


def log_event(prefix: str, message: str, *args: Any) -> None:
    """Always-on event log. Use for webhooks, replies, errors, etc."""
    if _CURRENT_RANK > _LEVEL_RANK["info"]:
        return
    _emit(prefix, _fmt(message, args))


def log_debug(prefix: str, message: str, *args: Any) -> None:
    """Print only when BRIDGE_LOG_LEVEL=debug. Use for heartbeat/tick loops."""
    if _CURRENT_RANK > _LEVEL_RANK["debug"]:
        return
    _emit(prefix, _fmt(message, args))


def log_warn(prefix: str, message: str, *args: Any) -> None:
    """Always printed."""
    _emit(prefix, _fmt(message, args))


_CHANGE_CACHE: dict[str, Any] = {}


def log_change(prefix: str, key: str, value: Any, message: str, *args: Any) -> None:
    """Print only when ``value`` differs from the last seen value for ``key``.

    Useful for things like "loaded reminders count=2 pending=0" which repeat
    dozens of times per hour without actually changing.
    """
    prev = _CHANGE_CACHE.get(key, _SENTINEL)
    if prev == value:
        return
    _CHANGE_CACHE[key] = value
    if _CURRENT_RANK > _LEVEL_RANK["info"]:
        return
    _emit(prefix, _fmt(message, args))


class _Sentinel:
    pass


_SENTINEL = _Sentinel()


__all__ = [
    "current_level",
    "log_event",
    "log_debug",
    "log_change",
    "log_warn",
]
