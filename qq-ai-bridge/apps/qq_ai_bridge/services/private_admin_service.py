"""Owner-only private chat admin commands for bridge configuration."""

from __future__ import annotations

import re
from typing import Any

from storage_utils import load_group_config_store, save_group_config_store

from apps.qq_ai_bridge.config.settings import GROUP_CONFIG_PATH, OWNER_QQ
from apps.qq_ai_bridge.services.group_strategy import normalize_group_strategy_config

_PROBABILITY_PATTERNS = {
    "reply_probability": re.compile(r"(?:回复|发言|回应)(?:频率|概率)?\s*[:：=]?\s*(0(?:\.\d+)?|1(?:\.0+)?)"),
    "silence_probability": re.compile(r"(?:沉默|静默|不回)(?:频率|概率)?\s*[:：=]?\s*(0(?:\.\d+)?|1(?:\.0+)?)"),
    "reaction_probability": re.compile(r"(?:表情|reaction)(?:频率|概率)?\s*[:：=]?\s*(0(?:\.\d+)?|1(?:\.0+)?)", re.IGNORECASE),
}


def maybe_handle_private_admin_command(user_id: Any, text: str) -> dict[str, Any] | None:
    """Handle safe owner-only group strategy commands from private chat."""
    query = re.sub(r"\s+", " ", str(text or "")).strip()
    if not _looks_like_admin_command(query):
        return None
    if str(user_id or "") != str(OWNER_QQ):
        return {
            "handled": True,
            "ok": False,
            "source": "private_admin_config",
            "reply": "这个配置命令只允许主人在私聊里使用。",
        }

    store = load_group_config_store(GROUP_CONFIG_PATH)
    match = _find_group(query, store)
    if not match:
        return {
            "handled": True,
            "ok": False,
            "source": "private_admin_config",
            "reply": "没找到这个群。可以用群号，或把群名说得更完整一点。",
        }

    group_id, group = match
    updates = _parse_updates(query)
    if not updates:
        return {
            "handled": True,
            "ok": True,
            "source": "private_admin_config",
            "reply": _format_strategy_reply(group_id, group),
        }

    merged = group.copy()
    if "reply_all_messages" in updates:
        merged["reply_all_messages"] = bool(updates["reply_all_messages"])

    strategy = normalize_group_strategy_config(merged)
    for key in ("reply_probability", "silence_probability", "reaction_probability"):
        if key in updates:
            strategy[key] = float(updates[key])
    merged["strategy"] = normalize_group_strategy_config({"strategy": strategy})
    merged.pop("strategy_config", None)
    store[group_id] = merged
    save_group_config_store(GROUP_CONFIG_PATH, store)
    return {
        "handled": True,
        "ok": True,
        "source": "private_admin_config",
        "reply": _format_strategy_reply(group_id, merged, prefix="已更新"),
        "group_id": group_id,
        "updates": updates,
    }


def _looks_like_admin_command(text: str) -> bool:
    if not text:
        return False
    return bool(
        ("策略" in text and any(token in text for token in ("查看", "调整", "改", "设置", "仅艾特", "全局")))
        or any(pattern.search(text) for pattern in _PROBABILITY_PATTERNS.values())
    )


def _find_group(query: str, store: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    id_match = re.search(r"\b(\d{6,})\b", query)
    if id_match:
        group_id = id_match.group(1)
        group = store.get(group_id)
        if isinstance(group, dict):
            return group_id, group

    candidates: list[tuple[int, str, dict[str, Any]]] = []
    compact_query = _compact(query)
    for group_id, raw in store.items():
        if group_id == "default" or not isinstance(raw, dict):
            continue
        name = str(raw.get("name") or "")
        compact_name = _compact(name)
        if not compact_name:
            continue
        if compact_name in compact_query or compact_query in compact_name:
            candidates.append((len(compact_name), str(group_id), raw))
            continue
        overlap = sum(1 for char in set(compact_name) if char in compact_query)
        if overlap >= min(4, max(2, len(set(compact_name)) // 2)):
            candidates.append((overlap, str(group_id), raw))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    _, group_id, group = candidates[0]
    return group_id, group


def _parse_updates(query: str) -> dict[str, Any]:
    updates: dict[str, Any] = {}
    if "仅艾特" in query or "只艾特" in query or "必须艾特" in query:
        updates["reply_all_messages"] = False
    elif "全局" in query or "全群" in query or "主动回复" in query:
        updates["reply_all_messages"] = True
    for key, pattern in _PROBABILITY_PATTERNS.items():
        match = pattern.search(query)
        if match:
            updates[key] = max(0.0, min(1.0, float(match.group(1))))
    return updates


def _format_strategy_reply(group_id: str, group: dict[str, Any], prefix: str = "当前策略") -> str:
    strategy = normalize_group_strategy_config(group)
    trigger = "全局" if bool(group.get("reply_all_messages", False)) else "仅艾特"
    name = str(group.get("name") or group_id)
    return (
        f"{prefix}：{name}({group_id})，触发={trigger}，"
        f"reply={strategy['reply_probability']:.2g} "
        f"silence={strategy['silence_probability']:.2g} "
        f"reaction={strategy['reaction_probability']:.2g}"
    )


def _compact(text: str) -> str:
    return re.sub(r"[\s（）()【】\\[\\]《》<>:：,，。.!！?？、_-]+", "", str(text or "")).lower()

