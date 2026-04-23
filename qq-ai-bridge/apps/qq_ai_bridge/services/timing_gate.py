"""Lightweight timing gate for group chat before LLM generation."""

from __future__ import annotations

import hashlib
import time
from typing import Iterable

from apps.qq_ai_bridge.services.quick_reply_policy import decide_quick_reply
from apps.qq_ai_bridge.services.reply_models import IncomingMessage, ReplyDecision, ReplyMode, TopicWindow


def evaluate_group_timing_gate(group_id, messages: Iterable, group_config: dict | None = None) -> ReplyDecision | None:
    """Return a local timing-gate decision or ``None`` to continue to LLM."""
    normalized = [_to_incoming_message(item) for item in messages]
    normalized = [item for item in normalized if item]
    if not normalized:
        return ReplyDecision(False, ReplyMode.NO_REPLY, "empty_batch", 1.0)

    # Respect explicit asks and richer topics by forwarding them to the main LLM.
    merged_text = " ".join(item.text for item in normalized).strip()
    if any(item.explicit_trigger for item in normalized):
        if any(token in merged_text for token in ("?", "？", "怎么", "为什么", "吗", "求")):
            return None

    topic = TopicWindow(
        group_id=int(group_id or 0),
        messages=normalized,
        started_at=time.monotonic(),
        last_event_at=time.monotonic(),
        replied=False,
        topic_key=_build_topic_key(group_id, normalized),
    )
    return decide_quick_reply(topic, group_config or {})


def _to_incoming_message(item) -> IncomingMessage | None:
    text = str(getattr(item, "text", "") or "").strip()
    if not text:
        return None
    return IncomingMessage(
        user_id=getattr(item, "user_id", None),
        sender_name=str(getattr(item, "sender_name", "") or "").strip() or str(getattr(item, "user_id", "?")),
        text=text,
        timestamp=int(getattr(item, "timestamp", 0) or 0),
        message_id=getattr(item, "message_id", None),
        explicit_trigger=bool(getattr(item, "explicit_trigger", False)),
    )


def _build_topic_key(group_id, messages: list[IncomingMessage]) -> str:
    seed = f"{group_id}|" + "|".join(f"{item.user_id}:{item.text}" for item in messages)
    return hashlib.md5(seed.encode("utf-8")).hexdigest()[:16]
