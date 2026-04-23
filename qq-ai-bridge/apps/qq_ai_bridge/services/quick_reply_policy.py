"""Local quick-reply rules for low-value group messages."""

from __future__ import annotations

import hashlib
import re

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text
from apps.qq_ai_bridge.services.reply_models import ReplyDecision, ReplyMode, TopicWindow

_QUESTION_TOKENS = ("?", "？", "吗", "咋", "怎么", "为何", "为什么", "求")
_LOW_VALUE_RE = re.compile(r"^(麦麦|在吗|在喵|在嘛|6|66|666|草|\?|？|哈+|欸|诶|啊|哦|嗯|.喵|喵)$", re.IGNORECASE)
_FILLER_RE = re.compile(r"^(确实|草|6|66|666|哈+|笑死|绷不住|典)$", re.IGNORECASE)
_CUTE_TOPIC_RE = re.compile(r"(麦麦|在喵|喵喵|猫猫|宝宝)", re.IGNORECASE)

_REACTION_EMOJI_MAP = {
    "laugh_cry": 0,
    "lollipop": 1,
    "red_button": 2,
    "lick_screen": 3,
}

_CUTE_TEMPLATES = ("在喵", "在呢", "麦麦路过", "喵一下")
_DRY_TEMPLATES = ("收到", "行", "确实", "是有点")


def decide_quick_reply(topic: TopicWindow, group_config: dict) -> ReplyDecision | None:
    """Return a local reply decision for low-value topics, otherwise None."""
    if not topic.messages:
        return ReplyDecision(False, ReplyMode.NO_REPLY, "empty_topic", 1.0)

    last_text = normalize_query_text(topic.messages[-1].text)
    merged_text = normalize_query_text(" ".join(message.text for message in topic.messages))
    if not merged_text:
        return ReplyDecision(False, ReplyMode.NO_REPLY, "empty_topic", 1.0)

    if any(token in merged_text for token in _QUESTION_TOKENS):
        return None

    if len(merged_text) >= 24 and not _LOW_VALUE_RE.fullmatch(last_text):
        return None

    if topic.replied:
        return ReplyDecision(False, ReplyMode.NO_REPLY, "topic_already_replied", 0.99)

    if _FILLER_RE.fullmatch(last_text):
        return ReplyDecision(True, ReplyMode.REACTION, "short_filler", 0.92, emoji_id=_REACTION_EMOJI_MAP["laugh_cry"])

    if _LOW_VALUE_RE.fullmatch(last_text):
        if _CUTE_TOPIC_RE.search(merged_text):
            if len(topic.messages) >= 2:
                return ReplyDecision(False, ReplyMode.NO_REPLY, "cute_topic_already_hot", 0.91)
            return ReplyDecision(
                True,
                ReplyMode.TEXT,
                "cute_short_text",
                0.88,
                text=_pick_template(merged_text, group_config, _CUTE_TEMPLATES),
            )
        return ReplyDecision(True, ReplyMode.REACTION, "short_meme", 0.86, emoji_id=_REACTION_EMOJI_MAP["red_button"])

    if len(merged_text) <= 8 and not any(message.explicit_trigger for message in topic.messages):
        return ReplyDecision(False, ReplyMode.NO_REPLY, "short_non_triggered", 0.84)
    return None


def _pick_template(seed_text: str, group_config: dict, templates: tuple[str, ...]) -> str:
    bias = str(group_config.get("quick_reply_style", "") or "").strip().lower()
    if bias == "dry":
        templates = _DRY_TEMPLATES
    digest = hashlib.md5(seed_text.encode("utf-8")).hexdigest()
    idx = int(digest[:8], 16) % len(templates)
    return templates[idx]
