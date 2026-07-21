"""Personalized read-only email triage and QQ delivery coordination."""

from __future__ import annotations

import inspect
import re
from datetime import datetime
from typing import Any, Callable, Literal

from apps.qq_ai_bridge.services.email_models import (
    EmailClassification,
    EmailEnvelope,
    EmailRuleDecision,
)
from apps.qq_ai_bridge.services.email_processing_store import EmailProcessingRecord

EmailRoute = Literal["immediate", "digest", "possible", "ignore"]

_URGENCY_PRIORITY = {"critical": 4, "high": 3, "medium": 2, "low": 1}
_STRONG_POSITIVE_SIGNALS = {
    "academic_action",
    "course_code",
    "direct_reply",
    "reply_thread",
    "research_competition",
    "watched_domain",
    "watched_sender",
}
_STRONG_POSITIVE_PREFIXES = (
    "cohort:",
    "interest:",
    "profile_adjustment:",
    "profile_positive:",
)


class EmailAutomationService:
    def __init__(
        self,
        *,
        imap_service: Any,
        archive_service: Any,
        preference_store: Any,
        rule_classifier: Any,
        semantic_classifier: Any,
        processing_store: Any,
        send_private: Callable[..., Any],
        owner_qq: int,
        mailbox: str,
        monitor_enabled: bool,
        immediate_push_enabled: bool,
        digest_push_enabled: bool,
        shadow_mode: bool,
        max_messages: int,
        semantic_batch_size: int = 20,
    ) -> None:
        self._imap = imap_service
        self._archive = archive_service
        self._preferences = preference_store
        self._rules = rule_classifier
        self._semantic = semantic_classifier
        self._store = processing_store
        self._send_private = send_private
        self._owner_qq = int(owner_qq)
        self._mailbox = str(mailbox or "INBOX").strip() or "INBOX"
        self._monitor_enabled = bool(monitor_enabled)
        self._immediate_push_enabled = bool(immediate_push_enabled)
        self._digest_push_enabled = bool(digest_push_enabled)
        self._shadow_mode = bool(shadow_mode)
        self._max_messages = max(1, int(max_messages))
        self._semantic_batch_size = max(1, int(semantic_batch_size))

    async def poll(self, now: datetime) -> None:
        if not self._monitor_enabled:
            return

        cursor = self._store.cursor(self._mailbox)
        batch = self._imap.fetch_new(last_uid=cursor.last_uid, limit=self._max_messages)
        if cursor.uid_validity and cursor.uid_validity != batch.uid_validity:
            self._store.reset_cursor(self._mailbox, batch.uid_validity)
            batch = self._imap.fetch_new(last_uid=0, limit=self._max_messages)

        profile = self._preferences.load()
        for fetched in batch.messages:
            envelope = fetched.envelope
            self._archive.archive_envelope(envelope)
            record = self._store.observe(
                self._mailbox,
                batch.uid_validity,
                fetched.uid,
                envelope,
            )
            if record.delivery_state in {"ignored", "immediate_sent", "digest_sent"}:
                continue
            decision = record.rule_decision
            if decision is None:
                decision = self._rules.classify(envelope, profile)
                self._store.save_rule_decision(record.alias, decision)
            if decision.eligibility != "semantic_required":
                self._store.mark_ignored(record.alias, decision.eligibility)

        await self._classify_pending()
        await self._deliver_pending_immediate(now)

    async def run_digest(self, now: datetime, slot: str) -> None:
        if not self._digest_push_enabled or self._shadow_mode:
            return
        slot_token = _digest_slot_token(now, slot)
        if self._store.was_digest_slot_sent(slot_token):
            return

        selected = _select_digest_records(self._store.pending_digest(now, lookback_hours=24))
        if not selected:
            return
        result = await self._send(_format_digest(selected))
        if _send_succeeded(result):
            self._store.mark_digest_sent(
                tuple(record.alias for record in selected),
                slot_token,
                now,
            )

    async def _classify_pending(self) -> None:
        candidates: list[tuple[str, EmailEnvelope, EmailRuleDecision]] = []
        for record in self._store.pending_analysis(limit=self._max_messages):
            envelope = self._archive.load_envelope(record.message_hash)
            if envelope is None or record.rule_decision is None:
                continue
            candidates.append((record.alias, envelope, record.rule_decision))

        for start in range(0, len(candidates), self._semantic_batch_size):
            chunk = candidates[start : start + self._semantic_batch_size]
            classifications = await self._semantic.classify(chunk)
            decisions = {alias: decision for alias, _, decision in chunk}
            for item in classifications:
                self._store.save_classification(item.alias, item)
                if route_classification(item, decisions.get(item.alias)) == "ignore":
                    self._store.mark_ignored(item.alias, "semantic_low_value")

    async def _deliver_pending_immediate(self, now: datetime) -> None:
        if not self._immediate_push_enabled or self._shadow_mode:
            return
        for record in self._store.pending_digest(now, lookback_hours=24):
            if route_classification(record.classification, record.rule_decision) != "immediate":
                continue
            result = await self._send(_format_immediate(record))
            if _send_succeeded(result):
                self._store.mark_immediate_sent(record.alias, now)

    async def _send(self, text: str) -> Any:
        result = self._send_private(
            self._owner_qq,
            text,
            quiet=True,
            redact_content=True,
        )
        return await result if inspect.isawaitable(result) else result


def route_classification(
    classification: EmailClassification | None,
    decision: EmailRuleDecision | None,
) -> EmailRoute:
    if classification is None:
        return "ignore"
    if classification.relevance_score >= 80 and classification.urgency in {"high", "critical"}:
        return "immediate"
    if classification.relevance_score >= 60:
        return "digest"
    if classification.relevance_score >= 40 and _has_strong_positive_signal(decision):
        return "possible"
    return "ignore"


def _has_strong_positive_signal(decision: EmailRuleDecision | None) -> bool:
    if decision is None:
        return False
    return any(
        signal in _STRONG_POSITIVE_SIGNALS
        or any(signal.startswith(prefix) for prefix in _STRONG_POSITIVE_PREFIXES)
        for signal in decision.positive_signals
    )


def _select_digest_records(
    records: tuple[EmailProcessingRecord, ...],
) -> tuple[EmailProcessingRecord, ...]:
    ordered = sorted(records, key=_priority_key)
    eligible = [
        record
        for record in ordered
        if route_classification(record.classification, record.rule_decision) != "ignore"
    ]
    action = [record for record in eligible if _requires_action(record.classification)][:3]
    used = {record.alias for record in action}
    relevant = [
        record
        for record in eligible
        if record.alias not in used
        and route_classification(record.classification, record.rule_decision)
        in {"immediate", "digest"}
    ][:4]
    used.update(record.alias for record in relevant)
    possible = [
        record
        for record in eligible
        if record.alias not in used
        and route_classification(record.classification, record.rule_decision) == "possible"
    ][:1]
    return tuple(action + relevant + possible)


def _priority_key(record: EmailProcessingRecord) -> tuple[int, int, float, str]:
    item = record.classification
    if item is None:
        return (0, 0, 0.0, record.alias)
    effective_at = record.sent_at or record.observed_at
    return (
        -_URGENCY_PRIORITY.get(item.urgency, 0),
        -item.relevance_score,
        -effective_at.timestamp(),
        record.alias,
    )


def _requires_action(item: EmailClassification | None) -> bool:
    return bool(item and (item.action.strip() or item.deadline is not None))


def _format_immediate(record: EmailProcessingRecord) -> str:
    item = record.classification
    if item is None:
        raise ValueError("cannot format an unclassified email")
    lines = [
        f"【重要邮件｜相关度 {item.relevance_score}｜紧急性 {_urgency_label(item.urgency)}】",
        f"[{record.alias}] {_one_line(item.concise_title, 120)}",
        f"发件人：{_one_line(record.sender_name, 120)}",
        f"摘要：{_one_line(item.summary, 300)}",
    ]
    if item.action.strip():
        lines.append(f"行动：{_one_line(item.action, 200)}")
    if item.deadline is not None:
        lines.append(f"截止：{item.deadline.isoformat()}")
    lines.append(f"相关原因：{_one_line(item.reason, 180)}")
    return "\n".join(lines)


def _format_digest(records: tuple[EmailProcessingRecord, ...]) -> str:
    action = [record for record in records if _requires_action(record.classification)]
    remaining = [record for record in records if record not in action]
    relevant = [
        record
        for record in remaining
        if route_classification(record.classification, record.rule_decision)
        in {"immediate", "digest"}
    ]
    possible = [record for record in remaining if record not in relevant]
    lines = ["【最近 24 小时邮件摘要】"]
    _append_digest_section(lines, "需要行动", action)
    _append_digest_section(lines, "与你相关", relevant)
    _append_digest_section(lines, "可能相关", possible)
    return "\n".join(lines)


def _append_digest_section(
    lines: list[str],
    heading: str,
    records: list[EmailProcessingRecord],
) -> None:
    if not records:
        return
    lines.extend(("", f"{heading}（{len(records)}）"))
    for record in records:
        item = record.classification
        if item is None:
            continue
        lines.append(
            f"- [{record.alias}] {_one_line(item.concise_title, 100)}｜"
            f"{_one_line(record.sender_name, 100)}｜相关度 {item.relevance_score}｜"
            f"紧急性 {_urgency_label(item.urgency)}"
        )
        lines.append(f"  {_one_line(item.summary, 220)}")
        if item.action.strip():
            lines.append(f"  行动：{_one_line(item.action, 160)}")


def _digest_slot_token(now: datetime, slot: str) -> str:
    normalized_slot = str(slot or "").strip()
    if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", normalized_slot):
        raise ValueError("digest slot must use HH:MM format")
    return f"email_digest:{now.date().isoformat()}:{normalized_slot}"


def _send_succeeded(result: Any) -> bool:
    return isinstance(result, dict) and result.get("ok") is True


def _urgency_label(value: str) -> str:
    return {"critical": "极高", "high": "高", "medium": "中", "low": "低"}.get(value, "未知")


def _one_line(value: str, limit: int) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


__all__ = ["EmailAutomationService", "route_classification"]
