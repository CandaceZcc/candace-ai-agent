"""Lightweight group-speaking strategy layer."""

from __future__ import annotations

import random
import re
from typing import Any


def group_strategy_decision(parsed_data: dict[str, Any]) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", str(parsed_data.get("text") or "")).strip()
    raw = str(parsed_data.get("raw_message") or "")
    mentioned_self = bool(parsed_data.get("is_mentioned"))
    at_targets = parsed_data.get("at_targets") or []

    if not text:
        return {"mode": "silence", "reason": "noise_empty"}
    if _addressed_to_other(at_targets, parsed_data.get("self_id"), raw):
        return {"mode": "silence", "reason": "addressed_to_other"}
    if mentioned_self or text.startswith(("/", "#")):
        return {"mode": "text", "reason": "explicit_trigger"}
    if any(token in text for token in ("?", "？", "怎么", "如何", "为什么", "吗", "么")):
        return {"mode": "text", "reason": "question"}
    if _emotion_short_text(text):
        return {"mode": "reaction", "reason": "emotion_short_text"}
    if _noise(text):
        return {"mode": "silence", "reason": "noise"}
    return {"mode": "delay_text", "reason": "ambient_reply", "delay_ms": random.randint(2000, 5000)}


def _emotion_short_text(text: str) -> bool:
    if len(text) > 12:
        return False
    return any(token in text for token in ("哈哈", "笑死", "草", "好耶", "呜呜", "哭了", "绝了", "离谱"))


def _noise(text: str) -> bool:
    if len(text) <= 2 and re.fullmatch(r"[\W_0-9a-zA-Z\u4e00-\u9fa5]+", text):
        return True
    return text in {"6", "66", "666", "ok", "OK", "嗯", "啊", "？", "?", "。"}


def _addressed_to_other(at_targets: list[Any], self_id: Any, raw: str) -> bool:
    if not at_targets:
        return False
    self_text = str(self_id or "")
    targets = {str(target) for target in at_targets if str(target or "")}
    return bool(targets) and (not self_text or self_text not in targets) and "[CQ:at" in raw
