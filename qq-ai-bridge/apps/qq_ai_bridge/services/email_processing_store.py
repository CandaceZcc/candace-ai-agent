"""Durable private state for personalized email automation."""

from __future__ import annotations

import hashlib
import json
import os
import threading
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Callable

from apps.qq_ai_bridge.services.email_models import (
    EmailClassification,
    EmailEnvelope,
    EmailRuleDecision,
)

_SCHEMA_VERSION = 1
_DELIVERY_STATES = {"observed", "pending", "ignored", "immediate_sent", "digest_sent"}


@dataclass(frozen=True)
class EmailMailboxCursor:
    uid_validity: str
    last_uid: int


@dataclass(frozen=True)
class EmailProcessingRecord:
    alias: str
    message_hash: str
    mailbox: str
    uid_validity: str
    uid: int
    sender_name: str
    sent_at: datetime | None
    observed_at: datetime
    rule_decision: EmailRuleDecision | None
    classification: EmailClassification | None
    delivery_state: str
    ignored_reason: str | None
    immediate_sent_at: datetime | None
    digest_sent_at: datetime | None


class EmailProcessingStore:
    def __init__(
        self,
        path: str | Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path).expanduser().resolve()
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        with self._lock:
            if not self.path.exists():
                _atomic_write_json(self.path, _default_payload())
            else:
                os.chmod(self.path, 0o600)

    def cursor(self, mailbox: str) -> EmailMailboxCursor:
        with self._lock:
            payload = self._load_unlocked()
        raw = payload.get("mailboxes", {}).get(str(mailbox), {})
        if not isinstance(raw, dict):
            return EmailMailboxCursor("", 0)
        return EmailMailboxCursor(
            str(raw.get("uid_validity", "")),
            max(0, int(raw.get("last_uid", 0))),
        )

    def reset_cursor(self, mailbox: str, uid_validity: str) -> None:
        mailbox_key = str(mailbox or "").strip()
        with self._lock:
            payload = self._load_unlocked()
            payload.setdefault("mailboxes", {})[mailbox_key] = {
                "uid_validity": str(uid_validity or ""),
                "last_uid": 0,
            }
            _atomic_write_json(self.path, payload)

    def observe(
        self,
        mailbox: str,
        uid_validity: str,
        uid: int,
        envelope: EmailEnvelope,
    ) -> EmailProcessingRecord:
        if int(uid) <= 0:
            raise ValueError("uid must be positive")
        mailbox_key = str(mailbox or "").strip()
        validity = str(uid_validity or "").strip()
        message_hash = _message_hash(envelope.message_id)
        with self._lock:
            payload = self._load_unlocked()
            cursors = payload.setdefault("mailboxes", {})
            cursor = cursors.setdefault(mailbox_key, {"uid_validity": validity, "last_uid": 0})
            if str(cursor.get("uid_validity", "")) != validity:
                cursor.clear()
                cursor.update({"uid_validity": validity, "last_uid": 0})
            cursor["last_uid"] = max(int(cursor.get("last_uid", 0)), int(uid))

            messages = payload.setdefault("messages", {})
            existing = messages.get(message_hash)
            if isinstance(existing, dict):
                _atomic_write_json(self.path, payload)
                return _record_from_payload(existing)

            alias_number = max(1000, int(payload.get("next_alias", 1000)))
            payload["next_alias"] = alias_number + 1
            record = {
                "alias": f"E-{alias_number}",
                "message_hash": message_hash,
                "mailbox": mailbox_key,
                "uid_validity": validity,
                "uid": int(uid),
                "sender_name": _sender_display_name(envelope.sender),
                "sent_at": _iso_or_none(envelope.sent_at),
                "observed_at": _as_aware(self._now()).isoformat(),
                "rule_decision": None,
                "classification": None,
                "delivery_state": "observed",
                "ignored_reason": None,
                "immediate_sent_at": None,
                "digest_sent_at": None,
            }
            messages[message_hash] = record
            _atomic_write_json(self.path, payload)
            return _record_from_payload(record)

    def save_rule_decision(self, alias: str, decision: EmailRuleDecision) -> None:
        self._update_record(
            alias,
            lambda record: record.update(rule_decision=_serialize_rule(decision)),
        )

    def save_classification(
        self,
        alias: str,
        classification: EmailClassification,
    ) -> None:
        normalized_alias = str(alias or "").strip().upper()
        if classification.alias != normalized_alias:
            raise ValueError("classification alias mismatch")

        def mutate(record: dict[str, Any]) -> None:
            record["classification"] = _serialize_classification(classification)
            if record.get("delivery_state") in {"observed", "pending"}:
                record["delivery_state"] = "pending"

        self._update_record(normalized_alias, mutate)

    def mark_ignored(self, alias: str, reason: str) -> None:
        def mutate(record: dict[str, Any]) -> None:
            record["delivery_state"] = "ignored"
            record["ignored_reason"] = str(reason or "ignored")[:100]

        self._update_record(alias, mutate)

    def mark_immediate_sent(self, alias: str, sent_at: datetime) -> None:
        def mutate(record: dict[str, Any]) -> None:
            record["delivery_state"] = "immediate_sent"
            record["immediate_sent_at"] = _as_aware(sent_at).isoformat()

        self._update_record(alias, mutate)

    def pending_analysis(self, limit: int = 100) -> tuple[EmailProcessingRecord, ...]:
        if int(limit) <= 0:
            raise ValueError("limit must be positive")
        with self._lock:
            payload = self._load_unlocked()
        records = []
        for raw in payload.get("messages", {}).values():
            if not isinstance(raw, dict):
                continue
            record = _record_from_payload(raw)
            if (
                record.delivery_state in {"observed", "pending"}
                and record.classification is None
                and record.rule_decision is not None
                and record.rule_decision.eligibility == "semantic_required"
            ):
                records.append(record)
        records.sort(key=lambda item: (item.observed_at, item.alias))
        return tuple(records[: int(limit)])

    def pending_digest(
        self,
        now: datetime,
        lookback_hours: int = 24,
    ) -> tuple[EmailProcessingRecord, ...]:
        if int(lookback_hours) <= 0:
            raise ValueError("lookback_hours must be positive")
        cutoff = _as_aware(now) - timedelta(hours=int(lookback_hours))
        with self._lock:
            payload = self._load_unlocked()
        records = []
        for raw in payload.get("messages", {}).values():
            if not isinstance(raw, dict):
                continue
            record = _record_from_payload(raw)
            effective_at = record.sent_at or record.observed_at
            if (
                record.delivery_state == "pending"
                and record.classification is not None
                and record.classification.relevance_score >= 40
                and effective_at >= cutoff
            ):
                records.append(record)
        records.sort(key=lambda item: (item.sent_at or item.observed_at, item.alias))
        return tuple(records)

    def mark_digest_sent(
        self,
        aliases: tuple[str, ...],
        slot_token: str,
        sent_at: datetime,
    ) -> None:
        normalized_aliases = {str(alias).strip().upper() for alias in aliases}
        with self._lock:
            payload = self._load_unlocked()
            for record in payload.get("messages", {}).values():
                if not isinstance(record, dict) or record.get("alias") not in normalized_aliases:
                    continue
                record["delivery_state"] = "digest_sent"
                record["digest_sent_at"] = _as_aware(sent_at).isoformat()
            payload.setdefault("digest_slots", {})[str(slot_token)] = _as_aware(sent_at).isoformat()
            _atomic_write_json(self.path, payload)

    def was_digest_slot_sent(self, slot_token: str) -> bool:
        with self._lock:
            payload = self._load_unlocked()
        return str(slot_token) in payload.get("digest_slots", {})

    def find_by_alias(self, alias: str) -> EmailProcessingRecord | None:
        normalized_alias = str(alias or "").strip().upper()
        with self._lock:
            payload = self._load_unlocked()
        for raw in payload.get("messages", {}).values():
            if isinstance(raw, dict) and raw.get("alias") == normalized_alias:
                return _record_from_payload(raw)
        return None

    def _update_record(self, alias: str, mutator: Callable[[dict[str, Any]], None]) -> None:
        normalized_alias = str(alias or "").strip().upper()
        with self._lock:
            payload = self._load_unlocked()
            for record in payload.get("messages", {}).values():
                if isinstance(record, dict) and record.get("alias") == normalized_alias:
                    mutator(record)
                    _atomic_write_json(self.path, payload)
                    return
        raise KeyError(f"unknown email alias: {normalized_alias}")

    def _load_unlocked(self) -> dict[str, Any]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported email processing state")
        return payload


def _default_payload() -> dict[str, Any]:
    return {
        "schema_version": _SCHEMA_VERSION,
        "next_alias": 1000,
        "mailboxes": {},
        "messages": {},
        "digest_slots": {},
        "alerts": {},
    }


def _message_hash(message_id: str) -> str:
    normalized = str(message_id or "").strip()
    if not normalized:
        raise ValueError("message_id must not be empty")
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _sender_display_name(sender: str) -> str:
    display_name, _ = parseaddr(str(sender or ""))
    return display_name.strip()[:200] or "未命名发件人"


def _record_from_payload(raw: dict[str, Any]) -> EmailProcessingRecord:
    delivery_state = str(raw.get("delivery_state", "observed"))
    if delivery_state not in _DELIVERY_STATES:
        raise ValueError("invalid delivery state")
    return EmailProcessingRecord(
        alias=str(raw["alias"]),
        message_hash=str(raw["message_hash"]),
        mailbox=str(raw["mailbox"]),
        uid_validity=str(raw["uid_validity"]),
        uid=int(raw["uid"]),
        sender_name=str(raw.get("sender_name", "未命名发件人")),
        sent_at=_parse_optional_datetime(raw.get("sent_at")),
        observed_at=_parse_datetime(raw["observed_at"]),
        rule_decision=_parse_rule(raw.get("rule_decision")),
        classification=_parse_classification(raw.get("classification")),
        delivery_state=delivery_state,
        ignored_reason=str(raw["ignored_reason"]) if raw.get("ignored_reason") else None,
        immediate_sent_at=_parse_optional_datetime(raw.get("immediate_sent_at")),
        digest_sent_at=_parse_optional_datetime(raw.get("digest_sent_at")),
    )


def _serialize_rule(decision: EmailRuleDecision) -> dict[str, Any]:
    return {
        "initial_score": decision.initial_score,
        "eligibility": decision.eligibility,
        "positive_signals": list(decision.positive_signals),
        "negative_signals": list(decision.negative_signals),
    }


def _parse_rule(raw: Any) -> EmailRuleDecision | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("invalid rule decision")
    return EmailRuleDecision(
        int(raw["initial_score"]),
        str(raw["eligibility"]),
        tuple(str(value) for value in raw.get("positive_signals", [])),
        tuple(str(value) for value in raw.get("negative_signals", [])),
    )


def _serialize_classification(classification: EmailClassification) -> dict[str, Any]:
    return {
        "alias": classification.alias,
        "relevance_score": classification.relevance_score,
        "urgency": classification.urgency,
        "category": classification.category,
        "concise_title": classification.concise_title,
        "summary": classification.summary,
        "action": classification.action,
        "deadline": _iso_or_none(classification.deadline),
        "reason": classification.reason,
        "confidence": classification.confidence,
    }


def _parse_classification(raw: Any) -> EmailClassification | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise ValueError("invalid email classification")
    return EmailClassification(
        alias=str(raw["alias"]),
        relevance_score=int(raw["relevance_score"]),
        urgency=str(raw["urgency"]),
        category=str(raw["category"]),
        concise_title=str(raw["concise_title"]),
        summary=str(raw["summary"]),
        action=str(raw.get("action", "")),
        deadline=_parse_optional_datetime(raw.get("deadline")),
        reason=str(raw.get("reason", "")),
        confidence=float(raw["confidence"]),
    )


def _as_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _iso_or_none(value: datetime | None) -> str | None:
    return _as_aware(value).isoformat() if value is not None else None


def _parse_optional_datetime(value: Any) -> datetime | None:
    return _parse_datetime(value) if value else None


def _parse_datetime(value: Any) -> datetime:
    return _as_aware(datetime.fromisoformat(str(value)))


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(temp_path, path)
        os.chmod(path, 0o600)
    finally:
        if temp_path.exists():
            temp_path.unlink()


__all__ = [
    "EmailMailboxCursor",
    "EmailProcessingRecord",
    "EmailProcessingStore",
]
