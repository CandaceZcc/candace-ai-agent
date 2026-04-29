"""Unified response action protocol and executors."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import Enum

from apps.qq_ai_bridge.adapters.napcat_client import (
    react_message_with_multiple_emojis,
    send_group_msg,
    send_private_msg,
)
from apps.qq_ai_bridge.services.emoji_service import build_face_sequence


class ActionKind(str, Enum):
    TEXT = "text"
    REACTION = "reaction"
    NO_REPLY = "no_reply"


@dataclass
class ResponseAction:
    kind: ActionKind
    text: str = ""
    reaction_count: int = 1
    preferred_order: tuple[str, ...] = ()
    reason: str = ""


_LEGACY_EMOJI_TAG_PATTERN = re.compile(r"\[emoji:[^\]]+\]", re.IGNORECASE)
_MARKDOWN_BULLET_PATTERN = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)、]\s+)")


# parse_llm_response_action：解析模型动作协议
def parse_llm_response_action(raw_text: str, *, surface: str = "group") -> ResponseAction:
    """Parse LLM output into strict action protocol.

    Accepts only JSON action protocol or plain text.
    Legacy tags like `[emoji:doge]` are treated as NO_REPLY to avoid
    leaking control tags into user-visible messages.
    """
    text = str(raw_text or "").strip()
    if not text:
        return ResponseAction(kind=ActionKind.NO_REPLY, reason="empty_reply")
    if "[[NO_REPLY]]" in text:
        return ResponseAction(kind=ActionKind.NO_REPLY, reason="explicit_no_reply_token")
    if _LEGACY_EMOJI_TAG_PATTERN.search(text):
        return ResponseAction(kind=ActionKind.NO_REPLY, reason="legacy_emoji_tag_blocked")

    obj = _parse_json_object(text)
    if obj is None:
        cleaned = sanitize_model_visible_text(text, surface=surface)
        if not cleaned:
            return ResponseAction(kind=ActionKind.NO_REPLY, reason="empty_plain_text")
        return ResponseAction(kind=ActionKind.TEXT, text=cleaned, reason="plain_text")

    action_name = str(obj.get("action") or obj.get("mode") or obj.get("kind") or "").strip().lower()
    if action_name in {"no_reply", "silence"}:
        return ResponseAction(kind=ActionKind.NO_REPLY, reason=str(obj.get("reason", ""))[:40])
    if action_name == "reaction":
        count = _safe_int(obj.get("reaction_count") or obj.get("count") or 1, default=1, min_value=1, max_value=4)
        preferred = obj.get("preferred_order") or obj.get("preferred") or ()
        preferred_order: tuple[str, ...] = ()
        if isinstance(preferred, list):
            preferred_order = tuple(str(item).strip() for item in preferred if str(item).strip())
        elif isinstance(preferred, str) and preferred.strip():
            preferred_order = (preferred.strip(),)
        return ResponseAction(
            kind=ActionKind.REACTION,
            reaction_count=count,
            preferred_order=preferred_order,
            reason=str(obj.get("reason", ""))[:40],
        )
    if action_name == "text":
        message = sanitize_model_visible_text(str(obj.get("text") or obj.get("message") or "").strip(), surface=surface)
        if not message:
            return ResponseAction(kind=ActionKind.NO_REPLY, reason="empty_text_action")
        return ResponseAction(kind=ActionKind.TEXT, text=message, reason=str(obj.get("reason", ""))[:40])

    # JSON that is not in the allowlisted action protocol is rejected instead
    # of being leaked as user-visible protocol/control text.
    return ResponseAction(kind=ActionKind.NO_REPLY, reason="unknown_json_action")


def sanitize_model_visible_text(text: str, *, surface: str = "group") -> str:
    """Collapse model protocol/markdown-ish output into a QQ-safe plain reply."""
    raw = str(text or "").strip()
    if not raw:
        return ""
    raw = re.sub(r"```(?:[a-zA-Z0-9_-]+)?\s*([\s\S]*?)```", r"\1", raw).strip()
    raw = re.sub(r"`([^`]+)`", r"\1", raw)
    raw = re.sub(r"\*\*([^*]+)\*\*", r"\1", raw)
    raw = re.sub(r"^#{1,6}\s*", "", raw, flags=re.MULTILINE)
    lines: list[str] = []
    for line in raw.splitlines():
        cleaned = _clean_visible_line(line, surface=surface)
        if cleaned:
            lines.append(cleaned)
    if not lines:
        return ""
    if surface == "private":
        return "\n".join(lines).strip()
    if len(lines) == 1:
        return lines[0]
    compact = "；".join(lines[:4])
    return re.sub(r"\s+", " ", compact).strip()


def _clean_visible_line(line: str, *, surface: str) -> str:
    cleaned = str(line or "").strip()
    if not cleaned:
        return ""
    if surface == "private" and re.fullmatch(r"\|?\s*:?-{2,}:?\s*(?:\|\s*:?-{2,}:?\s*)+\|?", cleaned):
        return ""
    if surface == "private" and cleaned.startswith("|") and cleaned.endswith("|"):
        cells = [cell.strip() for cell in cleaned.strip("|").split("|")]
        cells = [cell for cell in cells if cell]
        return " ".join(cells)
    cleaned = _MARKDOWN_BULLET_PATTERN.sub("", cleaned).strip()
    return cleaned


# _parse_json_object：解析JSON对象
def _parse_json_object(text: str) -> dict | None:
    try:
        obj = json.loads(text)
    except Exception:
        return None
    if not isinstance(obj, dict):
        return None
    return obj


# _safe_int：安全处理整数
def _safe_int(value, default: int, min_value: int, max_value: int) -> int:
    try:
        iv = int(value)
    except Exception:
        iv = default
    iv = max(min_value, iv)
    iv = min(max_value, iv)
    return iv


# execute_group_action：执行群聊回复动作
def execute_group_action(
    group_id,
    action: ResponseAction,
    *,
    target_message_id: int | None,
    quiet: bool,
    force_parts: int | None = None,
    reply_to_message_id: int | None = None,
) -> dict:
    if action.kind == ActionKind.NO_REPLY:
        return {"ok": True, "mode": ActionKind.NO_REPLY.value}
    if action.kind == ActionKind.REACTION:
        if not target_message_id:
            return {"ok": False, "mode": ActionKind.REACTION.value, "reason": "missing_target_message_id"}
        result = react_message_with_multiple_emojis(
            target_message_id,
            count=max(1, int(action.reaction_count or 1)),
            quiet=quiet,
            preferred_order=action.preferred_order or ("laugh_cry", "red_button", "lollipop", "lick_screen"),
            preserve_order=bool(action.preferred_order),
        )
        return {
            "ok": bool(result.get("ok")),
            "mode": ActionKind.REACTION.value,
            "applied_count": int(result.get("applied_count", 0)),
            "emoji_names": result.get("emoji_names", []),
        }
    result = send_group_msg(
        group_id,
        action.text,
        quiet=quiet,
        force_parts=force_parts,
        reply_to_message_id=reply_to_message_id,
    )
    if isinstance(result, dict):
        return {"mode": ActionKind.TEXT.value, **result}
    return {"ok": True, "mode": ActionKind.TEXT.value}


# execute_private_action：执行私聊回复动作
def execute_private_action(
    user_id,
    action: ResponseAction,
    *,
    target_message_id: int | None,
    quiet: bool,
    reaction_fallback_reply_face: bool = True,
    force_parts: int | None = None,
) -> dict:
    if action.kind == ActionKind.NO_REPLY:
        return {"ok": True, "mode": ActionKind.NO_REPLY.value}
    if action.kind == ActionKind.REACTION:
        if not target_message_id:
            return {"ok": False, "mode": ActionKind.REACTION.value, "reason": "missing_target_message_id"}
        result = react_message_with_multiple_emojis(
            target_message_id,
            count=max(1, int(action.reaction_count or 1)),
            quiet=quiet,
            preferred_order=action.preferred_order or ("laugh_cry", "red_button", "lollipop", "lick_screen"),
            preserve_order=bool(action.preferred_order),
        )
        applied_count = int(result.get("applied_count", 0))
        if applied_count > 0 and reaction_fallback_reply_face:
            faces = build_face_sequence(
                seed=f"private-reaction-fallback:{user_id}:{target_message_id}",
                count=applied_count,
            )
            send_private_msg(
                user_id,
                "\n\n".join(faces),
                quiet=quiet,
                reply_to_message_id=target_message_id,
            )
        return {
            "ok": bool(result.get("ok")),
            "mode": ActionKind.REACTION.value,
            "applied_count": applied_count,
            "emoji_names": result.get("emoji_names", []),
        }
    result = send_private_msg(user_id, action.text, quiet=quiet, force_parts=force_parts)
    if isinstance(result, dict):
        return {"mode": ActionKind.TEXT.value, **result}
    return {"ok": True, "mode": ActionKind.TEXT.value}
