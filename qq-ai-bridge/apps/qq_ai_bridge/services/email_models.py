"""Immutable domain values for read-only campus email digests."""

from __future__ import annotations

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
class EmailDigest:
    period_label: str
    message_count: int
    summary_text: str
    source_message_ids: tuple[str, ...]
    from_cache: bool


EmailCommandKind = Literal["query", "status", "help", "invalid", "no_match"]


@dataclass(frozen=True)
class EmailCommand:
    kind: EmailCommandKind
    query: EmailQuery | None = None
    period_label: str = ""


__all__ = [
    "EmailAttachment",
    "EmailCommand",
    "EmailDigest",
    "EmailEnvelope",
    "EmailQuery",
]
