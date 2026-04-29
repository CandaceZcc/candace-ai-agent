"""Lightweight expression selector for short group replies."""

from __future__ import annotations

import hashlib

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text

_PLAIN_REPLY_TEMPLATES = {
    "ack": ("ok", "行", "是有点", "何意味"),
    "question": ("这就有点怪了", "有点那个", "这得看情况", "像那么回事"),
    "image": ("何意味", "懂你意思", "顺", "？"),
    "meme": ("典", "绷", "有点典", "经典皮肤"),
}


def select_group_expression(reply: str, merged_text: str, group_config: dict | None = None) -> str:
    """Gently rewrite flat short replies into more natural chat expressions."""
    normalized_reply = normalize_query_text(reply)
    if not normalized_reply or "[[NO_REPLY]]" in normalized_reply:
        return normalized_reply
    if len(normalized_reply) > 18:
        return normalized_reply
    if any(punct in normalized_reply for punct in ("\n", "。", "！", "?", "？", "：")):
        return normalized_reply

    persona_intensity = _parse_persona_intensity(group_config or {})
    if persona_intensity < 20:
        return normalized_reply

    if normalized_reply not in {"收到", "行", "嗯", "哈哈", "有点离谱", "我看到了"}:
        return normalized_reply

    scene = _infer_scene(merged_text)
    templates = _PLAIN_REPLY_TEMPLATES.get(scene, _PLAIN_REPLY_TEMPLATES["ack"])
    if persona_intensity < 45:
        templates = templates[:2]
    idx = _stable_index(f"{merged_text}|{normalized_reply}|{persona_intensity}", len(templates))
    return templates[idx]


def _infer_scene(merged_text: str) -> str:
    text = normalize_query_text(merged_text)
    if any(token in text for token in ("图", "图片", "截图", "表情", "梗图")):
        return "image"
    if any(token in text for token in ("?", "？", "怎么", "为什么", "吗", "啥")):
        return "question"
    if any(token in text for token in ("典", "绷", "草", "哈哈", "笑死")):
        return "meme"
    return "ack"


def _stable_index(seed: str, size: int) -> int:
    digest = hashlib.md5(seed.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % max(size, 1)


def _parse_persona_intensity(group_config: dict) -> int:
    try:
        return max(0, min(100, int(group_config.get("persona_intensity", 35))))
    except (TypeError, ValueError):
        return 35
