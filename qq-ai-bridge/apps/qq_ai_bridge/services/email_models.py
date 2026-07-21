"""Immutable domain values for read-only campus email digests."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal


@dataclass(frozen=True)
class EmailQuery:
    start_date: date
    end_date: date
    limit: int
    refresh: bool = False

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")
        if self.limit <= 0:
            raise ValueError("limit must be positive")


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True)
class EmailEnvelope:
    message_id: str
    subject: str
    sender: str
    recipients: tuple[str, ...]
    sent_at: datetime | None
    body_text: str
    attachments: tuple[EmailAttachment, ...]


@dataclass(frozen=True)
class EmailFetchedMessage:
    uid: int
    envelope: EmailEnvelope

    def __post_init__(self) -> None:
        if self.uid <= 0:
            raise ValueError("uid must be positive")


@dataclass(frozen=True)
class EmailUidBatch:
    uid_validity: str
    messages: tuple[EmailFetchedMessage, ...]

    def __post_init__(self) -> None:
        if not self.uid_validity.strip():
            raise ValueError("uid_validity must not be empty")


EmailRuleEligibility = Literal[
    "semantic_required",
    "explicit_hard_ignore",
    "deterministic_low_value",
]


@dataclass(frozen=True)
class EmailRuleDecision:
    initial_score: int
    eligibility: EmailRuleEligibility
    positive_signals: tuple[str, ...]
    negative_signals: tuple[str, ...]

    def __post_init__(self) -> None:
        if not 0 <= self.initial_score <= 100:
            raise ValueError("initial_score must be between 0 and 100")
        if self.eligibility not in {
            "semantic_required",
            "explicit_hard_ignore",
            "deterministic_low_value",
        }:
            raise ValueError("invalid email rule eligibility")


EmailUrgency = Literal["low", "medium", "high", "critical"]


@dataclass(frozen=True)
class EmailClassification:
    alias: str
    relevance_score: int
    urgency: EmailUrgency
    category: str
    concise_title: str
    summary: str
    action: str
    deadline: datetime | None
    reason: str
    confidence: float

    def __post_init__(self) -> None:
        if not re.fullmatch(r"E-\d{4,}", self.alias):
            raise ValueError("alias must use E-NNNN format")
        if not 0 <= self.relevance_score <= 100:
            raise ValueError("relevance_score must be between 0 and 100")
        if self.urgency not in {"low", "medium", "high", "critical"}:
            raise ValueError("invalid email urgency")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if (
            not self.category.strip()
            or not self.concise_title.strip()
            or not self.summary.strip()
            or not self.reason.strip()
        ):
            raise ValueError("classification text fields must not be empty")


@dataclass(frozen=True)
class EmailDigest:
    period_label: str
    message_count: int
    summary_text: str
    source_message_ids: tuple[str, ...]
    from_cache: bool


EmailCommandKind = Literal[
    "query",
    "status",
    "help",
    "feedback",
    "preferences",
    "invalid",
    "no_match",
]


@dataclass(frozen=True)
class EmailCommand:
    kind: EmailCommandKind
    query: EmailQuery | None = None
    period_label: str = ""
    alias: str = ""
    feedback_action: str = ""


__all__ = [
    "EmailAttachment",
    "EmailCommand",
    "EmailClassification",
    "EmailDigest",
    "EmailEnvelope",
    "EmailFetchedMessage",
    "EmailQuery",
    "EmailRuleDecision",
    "EmailUidBatch",
]
