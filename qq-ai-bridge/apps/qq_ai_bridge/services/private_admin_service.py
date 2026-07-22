"""Owner-only private chat admin commands for bridge configuration."""

from __future__ import annotations

import re
from typing import Any

from storage_utils import load_group_config_store, save_group_config_store

from apps.qq_ai_bridge.config.settings import GROUP_CONFIG_PATH, OWNER_QQ
from apps.qq_ai_bridge.services.barrage_6657_service import (
    DEFAULT_COOLDOWN_SECONDS,
    DEFAULT_DAILY_LIMIT,
    Barrage6657Store,
    sync_6657_barrages_safely,
)
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

    if _is_6657_sync_command(query):
        sync_result = sync_6657_barrages_safely(log=print)
        if not sync_result.get("ok"):
            return {
                "handled": True,
                "ok": False,
                "source": "private_admin_config",
                "reply": f"6657弹幕库同步失败：{sync_result.get('error') or '未知错误'}",
            }
        stats = Barrage6657Store().get_stats()
        return {
            "handled": True,
            "ok": True,
            "source": "private_admin_config",
            "reply": _format_6657_library_stats(stats, prefix="同步完成"),
            "stats": stats,
        }

    if _is_6657_library_status_command(query):
        stats = Barrage6657Store().get_stats()
        return {
            "handled": True,
            "ok": True,
            "source": "private_admin_config",
            "reply": _format_6657_library_stats(stats),
            "stats": stats,
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
        if "6657" in query:
            return {
                "handled": True,
                "ok": True,
                "source": "private_admin_config",
                "reply": _format_6657_group_reply(group_id, group),
                "group_id": group_id,
            }
        return {
            "handled": True,
            "ok": True,
            "source": "private_admin_config",
            "reply": _format_strategy_reply(group_id, group),
        }

    merged = group.copy()
    if "reply_all_messages" in updates:
        merged["reply_all_messages"] = bool(updates["reply_all_messages"])
    if "enable_6657_barrage" in updates:
        merged["enable_6657_barrage"] = bool(updates["enable_6657_barrage"])

    strategy = normalize_group_strategy_config(merged)
    for key in ("reply_probability", "silence_probability", "reaction_probability"):
        if key in updates:
            strategy[key] = float(updates[key])
    merged["strategy"] = normalize_group_strategy_config({"strategy": strategy})
    merged.pop("strategy_config", None)
    store[group_id] = merged
    save_group_config_store(GROUP_CONFIG_PATH, store)
    if "enable_6657_barrage" in updates:
        reply = _format_6657_group_reply(group_id, merged, prefix="已更新")
    else:
        reply = _format_strategy_reply(group_id, merged, prefix="已更新")
    return {
        "handled": True,
        "ok": True,
        "source": "private_admin_config",
        "reply": reply,
        "group_id": group_id,
        "updates": updates,
    }


def _looks_like_admin_command(text: str) -> bool:
    if not text:
        return False
    return bool(
        (
            "6657" in text
            and any(
                token in text
                for token in ("查看", "状态", "配置", "开启", "启用", "关闭", "停用", "同步", "更新")
            )
        )
        or
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
    if "6657" in query:
        if any(token in query for token in ("关闭", "停用", "禁用")):
            updates["enable_6657_barrage"] = False
        elif any(token in query for token in ("开启", "启用", "打开")):
            updates["enable_6657_barrage"] = True
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


def _is_6657_sync_command(query: str) -> bool:
    return (
        "6657" in query
        and "弹幕库" in query
        and any(token in query for token in ("同步", "更新"))
    )


def _is_6657_library_status_command(query: str) -> bool:
    return (
        "6657" in query
        and "弹幕库" in query
        and any(token in query for token in ("查看", "状态"))
    )


def _format_6657_group_reply(group_id: str, group: dict[str, Any], prefix: str = "当前配置") -> str:
    name = str(group.get("name") or group_id)
    enabled = "已开启" if group.get("enable_6657_barrage", False) else "未开启"
    cooldown = _safe_int(group.get("6657_cooldown_seconds"), DEFAULT_COOLDOWN_SECONDS)
    daily_limit = _safe_int(group.get("6657_daily_limit"), DEFAULT_DAILY_LIMIT)
    return (
        f"{prefix}：{name}({group_id})，6657弹幕={enabled}，"
        f"冷却={cooldown}秒，每日上限={daily_limit}"
    )


def _format_6657_library_stats(stats: dict[str, Any], prefix: str = "6657弹幕库") -> str:
    return (
        f"{prefix}：弹幕={_safe_int(stats.get('barrages'), 0)}，"
        f"标签={_safe_int(stats.get('tags'), 0)}，"
        f"热榜快照={_safe_int(stats.get('hot_snapshots'), 0)}"
    )


def _safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _compact(text: str) -> str:
    return re.sub(r"[\s（）()【】\\[\\]《》<>:：,，。.!！?？、_-]+", "", str(text or "")).lower()
