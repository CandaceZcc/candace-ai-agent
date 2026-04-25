"""Follow and learn from group message emoji-like notices."""

from __future__ import annotations

import json
import os
import time
from collections import OrderedDict

from apps.qq_ai_bridge.adapters.napcat_client import set_msg_emoji_like
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR

_RECENT_NOTICE_KEYS: OrderedDict[str, float] = OrderedDict()
_RECENT_NOTICE_LIMIT = 512
_RECENT_GROUP_MESSAGES: OrderedDict[str, dict] = OrderedDict()
_RECENT_GROUP_MESSAGE_LIMIT = 2048
_RECENT_GROUP_MESSAGE_TTL_SECONDS = 6 * 60 * 60


# handle_group_reaction_notice：处理群表情通知
def handle_group_reaction_notice(data: dict, group_config: dict | None = None, self_id=None, log=print) -> dict:
    """Optionally follow a group emoji-like notice and persist it as a style sample."""
    parsed = parse_group_reaction_notice(data)
    if not parsed:
        return {"handled": False, "reason": "unrecognized_notice"}

    message_context = find_recent_group_message(parsed.get("group_id"), parsed.get("message_id"))
    if message_context:
        parsed["message_context"] = message_context
        parsed["message_text"] = message_context.get("text", "")
        parsed["message_sender_name"] = message_context.get("sender_name", "")
        parsed["message_sender_id"] = message_context.get("user_id", "")

    _append_reaction_sample(parsed)

    cfg = group_config or {}
    if not bool(cfg.get("bot_can_reply", True)):
        return {"handled": True, "followed": False, "reason": "bot_reply_disabled", **parsed}
    if not bool(cfg.get("follow_group_reactions", False)):
        return {"handled": True, "followed": False, "reason": "disabled", **parsed}
    if self_id is not None and str(parsed.get("user_id", "")) == str(self_id):
        return {"handled": True, "followed": False, "reason": "self_notice", **parsed}
    if _is_duplicate_notice(parsed):
        return {"handled": True, "followed": False, "reason": "duplicate", **parsed}

    result = set_msg_emoji_like(parsed["message_id"], emoji_id=parsed["emoji_id"], quiet=not bool(cfg.get("reaction_notice_log", False)))
    followed = bool(result.get("ok"))
    if log and bool(cfg.get("reaction_notice_log", True)):
        log(
            f"[REACTION_FOLLOW] group_id={parsed.get('group_id')} message_id={parsed.get('message_id')} "
            f"emoji_id={parsed.get('emoji_id')} user_id={parsed.get('user_id')} followed={followed}"
        )
    return {"handled": True, "followed": followed, "result": result, **parsed}


# record_group_message_for_reaction_learning：记录表情学习上下文
def record_group_message_for_reaction_learning(
    *,
    group_id,
    message_id,
    user_id=None,
    sender_name: str = "",
    text: str = "",
    raw_message: str = "",
    timestamp=None,
) -> None:
    """Keep a short-lived message_id -> message snapshot for reaction learning."""
    if group_id in (None, "") or message_id in (None, ""):
        return
    key = _message_context_key(group_id, message_id)
    _RECENT_GROUP_MESSAGES[key] = {
        "group_id": str(group_id),
        "message_id": str(message_id),
        "user_id": str(user_id or ""),
        "sender_name": str(sender_name or ""),
        "text": str(text or ""),
        "raw_message": str(raw_message or ""),
        "timestamp": int(timestamp or time.time()),
        "recorded_at": int(time.time()),
    }
    _trim_recent_group_messages()


# find_recent_group_message：查找近期群消息
def find_recent_group_message(group_id, message_id) -> dict:
    if group_id in (None, "") or message_id in (None, ""):
        return {}
    _trim_recent_group_messages()
    return dict(_RECENT_GROUP_MESSAGES.get(_message_context_key(group_id, message_id), {}))


# parse_group_reaction_notice：解析群表情通知
def parse_group_reaction_notice(data: dict) -> dict:
    """Extract group reaction notice fields from common NapCat/OneBot shapes."""
    if str(data.get("notice_type", "")) != "group_msg_emoji_like":
        return {}

    group_id = _first_value(data, "group_id", "groupId")
    user_id = _first_value(data, "user_id", "userId", "operator_id", "operatorId")
    message_id = _first_value(data, "message_id", "messageId", "msg_id", "msgId")
    emoji_id = _first_value(data, "emoji_id", "emojiId", "face_id", "faceId", "id")

    likes = data.get("likes") or data.get("emoji_like_list") or data.get("emojiLikeList")
    if isinstance(likes, list) and likes:
        first = next((item for item in likes if isinstance(item, dict)), None)
        if first:
            emoji_id = emoji_id or _first_value(first, "emoji_id", "emojiId", "face_id", "faceId", "id")
            user_id = user_id or _first_value(first, "user_id", "userId", "tiny_id", "tinyId")

    if not (group_id and message_id and emoji_id):
        return {}
    return {
        "group_id": str(group_id),
        "user_id": str(user_id or ""),
        "message_id": str(message_id),
        "emoji_id": str(emoji_id),
        "raw_notice_type": str(data.get("notice_type", "")),
        "timestamp": int(data.get("time") or time.time()),
    }


# _first_value：取首个相关逻辑
def _first_value(data: dict, *keys: str):
    for key in keys:
        value = data.get(key)
        if value not in (None, ""):
            return value
    return None


# _is_duplicate_notice：判断相关逻辑
def _is_duplicate_notice(parsed: dict, ttl_seconds: int = 20) -> bool:
    now = time.time()
    key = f"{parsed.get('group_id')}:{parsed.get('message_id')}:{parsed.get('emoji_id')}:{parsed.get('user_id')}"
    expired = [item_key for item_key, ts in _RECENT_NOTICE_KEYS.items() if now - ts > ttl_seconds]
    for item_key in expired:
        _RECENT_NOTICE_KEYS.pop(item_key, None)
    if key in _RECENT_NOTICE_KEYS:
        return True
    _RECENT_NOTICE_KEYS[key] = now
    while len(_RECENT_NOTICE_KEYS) > _RECENT_NOTICE_LIMIT:
        _RECENT_NOTICE_KEYS.popitem(last=False)
    return False


# _message_context_key：消息上下文处理
def _message_context_key(group_id, message_id) -> str:
    return f"{group_id}:{message_id}"


# _trim_recent_group_messages：裁剪近期群聊消息
def _trim_recent_group_messages() -> None:
    now = time.time()
    expired = [
        key
        for key, item in _RECENT_GROUP_MESSAGES.items()
        if now - float(item.get("recorded_at", 0)) > _RECENT_GROUP_MESSAGE_TTL_SECONDS
    ]
    for key in expired:
        _RECENT_GROUP_MESSAGES.pop(key, None)
    while len(_RECENT_GROUP_MESSAGES) > _RECENT_GROUP_MESSAGE_LIMIT:
        _RECENT_GROUP_MESSAGES.popitem(last=False)


# _append_reaction_sample：追加reaction
def _append_reaction_sample(parsed: dict) -> None:
    logs_dir = os.path.join(BASE_DATA_DIR, "logs")
    os.makedirs(logs_dir, exist_ok=True)
    path = os.path.join(logs_dir, "group_reaction_samples.jsonl")
    payload = dict(parsed)
    payload.setdefault("logged_at", int(time.time()))
    try:
        with open(path, "a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except Exception:
        pass


__all__ = [
    "find_recent_group_message",
    "handle_group_reaction_notice",
    "parse_group_reaction_notice",
    "record_group_message_for_reaction_learning",
]
