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
