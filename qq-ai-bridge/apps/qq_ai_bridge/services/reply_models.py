"""Shared reply decision data models for group chat orchestration."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ReplyMode(str, Enum):
    """Unified group reply modes."""

    TEXT = "text"
    REACTION = "reaction"
    TEXT_PLUS_REACTION = "text_plus_reaction"
    NO_REPLY = "no_reply"


@dataclass
class ReplyDecision:
    """Decision outcome for one message or topic window."""

    should_reply: bool
    mode: ReplyMode
    reason: str
    confidence: float
    text: str | None = None
    emoji_id: int | None = None


@dataclass
class IncomingMessage:
    """Normalized inbound message used by topic-window logic."""

    user_id: int | None
    sender_name: str
    text: str
    timestamp: int
    message_id: int | None = None
    explicit_trigger: bool = False
    mentioned_self: bool = False
    has_image: bool = False
    image_urls: list[str] = field(default_factory=list)


@dataclass
class TopicWindow:
    """Merged topic cluster for one short group-chat window."""

    group_id: int
    messages: list[IncomingMessage]
    started_at: float
    last_event_at: float
    replied: bool
    topic_key: str


@dataclass
class ImageSocialClassification:
    """Phase-one image social classification result."""

    image_type: str
    social_intent: str
    suggested_action: str
    confidence: float
    reason: str
    short_text: str | None = None
    emoji_name: str | None = None

