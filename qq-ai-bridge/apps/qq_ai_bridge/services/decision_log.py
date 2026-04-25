"""Structured decision logs for group-chat observability."""

from __future__ import annotations

from typing import Any


# log_decision：记录决策
def log_decision(log=print, **fields: Any) -> None:
    """Emit one compact structured decision line."""
    ordered_keys = (
        "group_id",
        "topic_key",
        "content_type",
        "has_image",
        "image_type",
        "intent",
        "decision_mode",
        "reason",
        "used_llm",
        "used_vision",
        "latency_ms",
    )
    parts: list[str] = []
    seen: set[str] = set()
    for key in ordered_keys:
        if key not in fields:
            continue
        seen.add(key)
        parts.append(f"{key}={fields[key]}")
    for key, value in fields.items():
        if key in seen:
            continue
        parts.append(f"{key}={value}")
    log("[DECISION] " + " ".join(parts))

