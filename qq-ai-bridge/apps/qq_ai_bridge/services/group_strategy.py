"""Lightweight group-speaking strategy layer."""

from __future__ import annotations

import random
import re
import threading
import time
from typing import Any


DEFAULT_GROUP_STRATEGY: dict[str, Any] = {
    "reply_probability": 0.7,
    "silence_probability": 0.2,
    "reaction_probability": 0.1,
    "delay_min_ms": 300,
    "delay_max_ms": 2000,
    "context_window_sec": 5,
    "require_mention_for_reply": False,
    "cooldown_sec": 3,
}

_LAST_REPLY_LOCK = threading.Lock()
_LAST_REPLY_AT: dict[str, float] = {}


def normalize_group_strategy_config(group_config: dict[str, Any] | None) -> dict[str, Any]:
    raw = {}
    if isinstance(group_config, dict):
        strategy = group_config.get("strategy")
        if not isinstance(strategy, dict):
            strategy = group_config.get("strategy_config")
        if isinstance(strategy, dict):
            raw = strategy

    cfg = DEFAULT_GROUP_STRATEGY.copy()
    for key in ("reply_probability", "silence_probability", "reaction_probability"):
        cfg[key] = _clamp_float(raw.get(key, cfg[key]), 0.0, 1.0)
    for key in ("delay_min_ms", "delay_max_ms"):
        cfg[key] = _clamp_int(raw.get(key, cfg[key]), 0, 60000)
    cfg["context_window_sec"] = _clamp_int(raw.get("context_window_sec", cfg["context_window_sec"]), 1, 60)
    cfg["cooldown_sec"] = _clamp_int(raw.get("cooldown_sec", cfg["cooldown_sec"]), 0, 3600)
    cfg["require_mention_for_reply"] = _to_bool(raw.get("require_mention_for_reply", cfg["require_mention_for_reply"]))
    if cfg["delay_max_ms"] < cfg["delay_min_ms"]:
        cfg["delay_max_ms"] = cfg["delay_min_ms"]
    if _probability_total(cfg) <= 0:
        for key in ("reply_probability", "silence_probability", "reaction_probability"):
            cfg[key] = DEFAULT_GROUP_STRATEGY[key]
    return cfg


def group_strategy_decision(parsed_data: dict[str, Any], group_config: dict[str, Any] | None = None) -> dict[str, Any]:
    cfg = normalize_group_strategy_config(group_config)
    text = re.sub(r"\s+", " ", str(parsed_data.get("text") or "")).strip()
    raw = str(parsed_data.get("raw_message") or "")
    mentioned_self = bool(parsed_data.get("is_mentioned"))
    at_targets = parsed_data.get("at_targets") or []
    group_id = str(parsed_data.get("group_id") or "")
    explicit_trigger = bool(parsed_data.get("explicit_trigger") or mentioned_self or text.startswith(("/", "#")))
    allow_ambient = bool(parsed_data.get("allow_ambient") or (group_config or {}).get("reply_all_messages"))
    probabilities = _probabilities_payload(cfg)

    if not text:
        return _decision("silence", "noise_empty", cfg, probabilities=probabilities)
    if _addressed_to_other(at_targets, parsed_data.get("self_id"), raw):
        return _decision("silence", "addressed_to_other", cfg, probabilities=probabilities)
    if not allow_ambient and not explicit_trigger:
        return _decision("silence", "mention_only_not_triggered", cfg, probabilities=probabilities)
    if cfg["require_mention_for_reply"] and not explicit_trigger:
        return _decision("silence", "require_mention_for_reply", cfg, probabilities=probabilities)
    cooldown_remaining = _cooldown_remaining_ms(group_id, cfg["cooldown_sec"])
    if cooldown_remaining > 0:
        return _decision(
            "silence",
            "cooldown",
            cfg,
            probabilities=probabilities,
            cooldown_hit=True,
            cooldown_remaining_ms=cooldown_remaining,
        )
    if explicit_trigger:
        return _decision("text", "explicit_trigger", cfg, probabilities=probabilities)
    if any(token in text for token in ("?", "？", "怎么", "如何", "为什么", "吗", "么")):
        return _apply_probability("text", "question", cfg, probabilities)
    if _emotion_short_text(text):
        return _apply_probability("reaction", "emotion_short_text", cfg, probabilities)
    if _noise(text):
        return _decision("silence", "noise", cfg, probabilities=probabilities)
    return _apply_probability("delay_text", "ambient_reply", cfg, probabilities)


def record_group_strategy_reply(group_id: Any) -> None:
    key = str(group_id or "")
    if not key:
        return
    with _LAST_REPLY_LOCK:
        _LAST_REPLY_AT[key] = time.monotonic()


def reset_group_strategy_state() -> None:
    with _LAST_REPLY_LOCK:
        _LAST_REPLY_AT.clear()


def _apply_probability(
    preferred_mode: str,
    reason: str,
    cfg: dict[str, Any],
    probabilities: dict[str, float],
) -> dict[str, Any]:
    selected = _weighted_mode(cfg)
    mode = preferred_mode
    if selected == "silence":
        mode = "silence"
    elif selected == "reaction":
        mode = "reaction"
    elif selected == "text":
        mode = "delay_text" if preferred_mode == "delay_text" else "text"
    return _decision(mode, reason, cfg, probabilities=probabilities)


def _weighted_mode(cfg: dict[str, Any]) -> str:
    weights = [
        ("text", float(cfg["reply_probability"])),
        ("silence", float(cfg["silence_probability"])),
        ("reaction", float(cfg["reaction_probability"])),
    ]
    total = sum(max(0.0, weight) for _, weight in weights)
    if total <= 0:
        return "text"
    pick = random.uniform(0, total)
    cursor = 0.0
    for mode, weight in weights:
        cursor += max(0.0, weight)
        if pick <= cursor:
            return mode
    return "text"


def _decision(
    mode: str,
    reason: str,
    cfg: dict[str, Any],
    *,
    probabilities: dict[str, float],
    cooldown_hit: bool = False,
    cooldown_remaining_ms: int = 0,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "mode": mode,
        "reason": reason,
        "probabilities": probabilities,
        "context_window_sec": cfg["context_window_sec"],
        "cooldown_hit": cooldown_hit,
    }
    if cooldown_remaining_ms:
        result["cooldown_remaining_ms"] = cooldown_remaining_ms
    if mode == "delay_text":
        result["delay_ms"] = random.randint(int(cfg["delay_min_ms"]), int(cfg["delay_max_ms"]))
    return result


def _cooldown_remaining_ms(group_id: str, cooldown_sec: int) -> int:
    if not group_id or cooldown_sec <= 0:
        return 0
    with _LAST_REPLY_LOCK:
        last_at = _LAST_REPLY_AT.get(group_id)
    if not last_at:
        return 0
    elapsed = time.monotonic() - last_at
    remaining = float(cooldown_sec) - elapsed
    return max(0, int(remaining * 1000))


def _probabilities_payload(cfg: dict[str, Any]) -> dict[str, float]:
    return {
        "reply": float(cfg["reply_probability"]),
        "silence": float(cfg["silence_probability"]),
        "reaction": float(cfg["reaction_probability"]),
    }


def _probability_total(cfg: dict[str, Any]) -> float:
    return sum(float(cfg[key]) for key in ("reply_probability", "silence_probability", "reaction_probability"))


def _clamp_float(value: Any, minimum: float, maximum: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = minimum
    return min(maximum, max(minimum, parsed))


def _clamp_int(value: Any, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = minimum
    return min(maximum, max(minimum, parsed))


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value or "").strip().lower() in {"1", "true", "yes", "on", "y"}


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
