"""In-process command queue for VoCat device pull control."""

from __future__ import annotations

import re
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from apps.qq_ai_bridge.config.settings import VOCAT_COMMAND_QUEUE_MAX

_QUEUE_LOCK = threading.Lock()
_QUEUE: list[dict[str, Any]] = []
_STATUS_LOCK = threading.Lock()
_STATUS: dict[str, Any] = {
    "last_poll_at": None,
    "last_ack_at": None,
    "last_webhook_at": None,
    "last_query": "",
    "last_reply": "",
    "last_expression": "",
    "last_source": "",
    "last_remote_addr": "",
    "last_command_id": "",
    "last_command_type": "",
    "last_ack_ok": None,
    "poll_count": 0,
    "ack_count": 0,
}

_EXPRESSION_ALIASES = {
    "happy": "happy",
    "开心": "happy",
    "高兴": "happy",
    "neutral": "happy",
    "ok": "happy",
    "angry": "angry",
    "生气": "angry",
    "烦": "angry",
    "dizzy": "dizzy",
    "thinking": "dizzy",
    "思考": "dizzy",
    "sleep": "sleep",
    "困": "sleep",
    "睡觉": "sleep",
    "blink": "blink",
    "眨眼": "blink",
}


def normalize_vocat_expression(expression: str | int | None) -> str:
    raw = str(expression or "").strip()
    if not raw:
        return "happy"
    lowered = raw.lower()
    if lowered.isdigit():
        return lowered
    for key, value in _EXPRESSION_ALIASES.items():
        if key.lower() == lowered or key in raw:
            return value
    return "happy"


def select_vocat_expression(text: str) -> str:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return "happy"
    if any(token in normalized for token in ("睡", "晚安", "困", "休息")):
        return "sleep"
    if any(token in normalized for token in ("失败", "错误", "无法", "不能", "没法", "不支持", "没有权限")):
        return "dizzy"
    if any(token in normalized for token in ("生气", "讨厌", "离谱", "愤怒", "怒", "气死")):
        return "angry"
    if any(token in normalized for token in ("想", "查", "等", "处理中", "不知道", "稍等")):
        return "dizzy"
    if any(token in normalized for token in ("哈哈", "开心", "好耶", "可以", "已完成", "完成了")):
        return "happy"
    if "?" in normalized or "？" in normalized:
        return "blink"
    return "happy"


def enqueue_vocat_tts(
    text: str,
    *,
    source: str = "",
    expression: str | int | None = None,
    device_name: str = "",
) -> dict[str, Any]:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if not cleaned:
        return {"ok": False, "error": "empty_text"}
    command = _new_command(
        {
            "type": "tts",
            "text": cleaned[:500],
            "expression": normalize_vocat_expression(expression or select_vocat_expression(cleaned)),
            "source": source,
            "device_name": str(device_name or ""),
        }
    )
    return _enqueue(command)


def enqueue_vocat_expression(
    expression: str | int,
    *,
    source: str = "",
    device_name: str = "",
) -> dict[str, Any]:
    command = _new_command(
        {
            "type": "expression",
            "expression": normalize_vocat_expression(expression),
            "source": source,
            "device_name": str(device_name or ""),
        }
    )
    return _enqueue(command)


def poll_vocat_command(device_name: str = "") -> dict[str, Any] | None:
    target = str(device_name or "").strip()
    now = _utc_now()
    with _QUEUE_LOCK:
        for command in _QUEUE:
            command_device = str(command.get("device_name") or "").strip()
            if command_device and target and command_device != target:
                continue
            if command_device and not target:
                continue
            command["last_delivered_at"] = now
            command["delivery_count"] = int(command.get("delivery_count") or 0) + 1
            return dict(command)
    return None


def ack_vocat_command(command_id: str) -> dict[str, Any]:
    target = str(command_id or "").strip()
    if not target:
        return {"ok": False, "error": "missing_command_id"}
    with _QUEUE_LOCK:
        before = len(_QUEUE)
        _QUEUE[:] = [command for command in _QUEUE if command.get("id") != target]
        removed = before - len(_QUEUE)
        return {"ok": removed > 0, "removed": removed, "queue_size": len(_QUEUE)}


def get_vocat_queue_status() -> dict[str, Any]:
    with _QUEUE_LOCK:
        return {
            "ok": True,
            "queue_size": len(_QUEUE),
            "commands": [dict(command) for command in _QUEUE],
        }


def record_vocat_webhook(
    *,
    query: str = "",
    reply: str = "",
    expression: str | int | None = None,
    source: str = "",
    remote_addr: str = "",
    trace_id: str = "",
    model_reply: str = "",
) -> dict[str, Any]:
    with _STATUS_LOCK:
        _STATUS.update(
            {
                "last_webhook_at": _utc_now(),
                "last_query": _preview(query, 180),
                "last_reply": _preview(reply, 240),
                "last_expression": normalize_vocat_expression(expression),
                "last_source": str(source or ""),
                "last_remote_addr": str(remote_addr or ""),
                "last_trace_id": str(trace_id or ""),
                "last_model_reply": _preview(model_reply, 240),
            }
        )
        return dict(_STATUS)


def record_vocat_poll(*, command: dict[str, Any] | None = None, queue_size: int = 0) -> dict[str, Any]:
    with _STATUS_LOCK:
        _STATUS["last_poll_at"] = _utc_now()
        _STATUS["poll_count"] = int(_STATUS.get("poll_count") or 0) + 1
        if command:
            _STATUS["last_command_id"] = str(command.get("id") or "")
            _STATUS["last_command_type"] = str(command.get("type") or "")
            _STATUS["last_expression"] = normalize_vocat_expression(command.get("expression"))
        _STATUS["queue_size"] = max(0, int(queue_size or 0))
        return dict(_STATUS)


def record_vocat_ack(command_id: str = "", result: dict[str, Any] | None = None) -> dict[str, Any]:
    result = result or {}
    with _STATUS_LOCK:
        _STATUS["last_ack_at"] = _utc_now()
        _STATUS["ack_count"] = int(_STATUS.get("ack_count") or 0) + 1
        _STATUS["last_command_id"] = str(command_id or "")
        _STATUS["last_ack_ok"] = bool(result.get("ok"))
        if "queue_size" in result:
            _STATUS["queue_size"] = max(0, int(result.get("queue_size") or 0))
        return dict(_STATUS)


def get_vocat_runtime_status(*, online_window_seconds: int = 15) -> dict[str, Any]:
    queue_status = get_vocat_queue_status()
    with _STATUS_LOCK:
        status = dict(_STATUS)
    last_poll_at = status.get("last_poll_at")
    status.update(
        {
            "ok": True,
            "queue_size": queue_status["queue_size"],
            "device_online": _is_recent_utc(last_poll_at, online_window_seconds),
            "online_window_seconds": online_window_seconds,
        }
    )
    return status


def _new_command(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "created_at": _utc_now(),
        "delivery_count": 0,
        **payload,
    }


def _enqueue(command: dict[str, Any]) -> dict[str, Any]:
    with _QUEUE_LOCK:
        _QUEUE.append(command)
        max_size = max(1, VOCAT_COMMAND_QUEUE_MAX)
        if len(_QUEUE) > max_size:
            del _QUEUE[: len(_QUEUE) - max_size]
        return {
            "ok": True,
            "queued": True,
            "command_id": command["id"],
            "queue_size": len(_QUEUE),
            "command": dict(command),
        }


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _preview(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit].rstrip() + "..."


def _is_recent_utc(raw: str | None, window_seconds: int) -> bool:
    if not raw:
        return False
    try:
        parsed = datetime.fromisoformat(str(raw))
    except ValueError:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    return 0 <= delta.total_seconds() <= max(1, int(window_seconds))
