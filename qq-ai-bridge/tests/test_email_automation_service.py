import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.email_archive_service import EmailArchiveService
from apps.qq_ai_bridge.services.email_models import (
    EmailClassification,
    EmailEnvelope,
    EmailFetchedMessage,
    EmailRuleDecision,
    EmailUidBatch,
)
from apps.qq_ai_bridge.services.email_processing_store import EmailProcessingStore

NOW = datetime(2026, 7, 21, 12, 30, tzinfo=timezone(timedelta(hours=8)))


def envelope(number: int, *, message_id: str | None = None) -> EmailEnvelope:
    return EmailEnvelope(
        message_id=message_id or f"<synthetic-{number}@example.invalid>",
        subject=f"RAW PRIVATE SUBJECT {number}",
        sender=f"Teacher {number} <teacher{number}@example.invalid>",
        recipients=("student@example.invalid",),
        sent_at=NOW - timedelta(minutes=number),
        body_text=f"RAW PRIVATE BODY {number}",
        attachments=(),
    )


def rule(
    eligibility: str = "semantic_required",
    *,
    positive: tuple[str, ...] = ("interest:robotics",),
) -> EmailRuleDecision:
    return EmailRuleDecision(75, eligibility, positive, ())


def classification(
    alias: str,
    *,
    relevance: int = 85,
    urgency: str = "high",
    action: str = "今晚确认安排。",
    title: str | None = None,
) -> EmailClassification:
    return EmailClassification(
        alias=alias,
        relevance_score=relevance,
        urgency=urgency,
        category="course_change",
        concise_title=title or f"精简标题 {alias}",
        summary=f"精简摘要 {alias}",
        action=action,
        deadline=None,
        reason="与你的课程和专业方向相关",
        confidence=0.9,
    )


class FakeImap:
    def __init__(self, *batches: EmailUidBatch):
        self.batches = list(batches)
        self.calls: list[tuple[int, int]] = []

    def fetch_new(self, *, last_uid: int, limit: int) -> EmailUidBatch:
        self.calls.append((last_uid, limit))
        if self.batches:
            return self.batches.pop(0)
        return EmailUidBatch(uid_validity="44", messages=())


class FakePreferenceStore:
    def load(self):
        return object()


class FakeRuleClassifier:
    def __init__(self, decisions: dict[str, EmailRuleDecision] | None = None):
        self.decisions = decisions or {}

    def classify(self, message: EmailEnvelope, _profile) -> EmailRuleDecision:
        return self.decisions.get(message.message_id, rule())


class FakeSemanticClassifier:
    def __init__(self, *, fail_once: bool = False):
        self.fail_once = fail_once
        self.calls: list[list[tuple[str, EmailEnvelope, EmailRuleDecision]]] = []

    async def classify(self, candidates):
        self.calls.append(list(candidates))
        if self.fail_once:
            self.fail_once = False
            raise RuntimeError("synthetic model failure")
        return tuple(classification(alias) for alias, _, _ in candidates)


class TrackingArchive:
    def __init__(self, delegate, events):
        self.delegate = delegate
        self.events = events

    def archive_envelope(self, message):
        self.events.append(("archive", message.message_id))
        return self.delegate.archive_envelope(message)

    def load_envelope(self, message_hash):
        return self.delegate.load_envelope(message_hash)


class TrackingStore:
    def __init__(self, delegate, events):
        self.delegate = delegate
        self.events = events

    def observe(self, mailbox, uid_validity, uid, message):
        self.events.append(("observe", message.message_id))
        return self.delegate.observe(mailbox, uid_validity, uid, message)

    def __getattr__(self, name):
        return getattr(self.delegate, name)


class EmailAutomationServiceTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.archive = EmailArchiveService(root / "email")
        self.store = EmailProcessingStore(root / "automation-state.json", now=lambda: NOW)
        self.sent: list[tuple[int, str, dict[str, object]]] = []
        self.send_results: list[dict[str, object]] = []

    def tearDown(self):
        self.temp_dir.cleanup()

    def sender(self, user_id, text, **kwargs):
        self.sent.append((user_id, text, kwargs))
        if self.send_results:
            return self.send_results.pop(0)
        return {"ok": True}

    def service(
        self,
        *,
        imap=None,
        archive=None,
        store=None,
        rules=None,
        semantic=None,
        monitor_enabled=True,
        immediate_push_enabled=True,
        digest_push_enabled=True,
        shadow_mode=False,
    ):
        from apps.qq_ai_bridge.services.email_automation_service import EmailAutomationService

        return EmailAutomationService(
            imap_service=imap or FakeImap(),
            archive_service=archive or self.archive,
            preference_store=FakePreferenceStore(),
            rule_classifier=rules or FakeRuleClassifier(),
            semantic_classifier=semantic or FakeSemanticClassifier(),
            processing_store=store or self.store,
            send_private=self.sender,
            owner_qq=12345,
            mailbox="INBOX",
            monitor_enabled=monitor_enabled,
            immediate_push_enabled=immediate_push_enabled,
            digest_push_enabled=digest_push_enabled,
            shadow_mode=shadow_mode,
            max_messages=100,
            semantic_batch_size=20,
        )

    async def test_disabled_monitor_does_not_read_mail(self):
        imap = FakeImap()

        await self.service(imap=imap, monitor_enabled=False).poll(NOW)

        self.assertEqual(imap.calls, [])

    async def test_archives_before_advancing_processing_cursor(self):
        message = envelope(1)
        events = []
        archive = TrackingArchive(self.archive, events)
        store = TrackingStore(self.store, events)
        imap = FakeImap(
            EmailUidBatch("44", (EmailFetchedMessage(uid=17, envelope=message),))
        )

        await self.service(imap=imap, archive=archive, store=store).poll(NOW)

        self.assertEqual(
            events[:2],
            [("archive", message.message_id), ("observe", message.message_id)],
        )

    async def test_hard_ignore_skips_model_and_delivery(self):
        message = envelope(1)
        semantic = FakeSemanticClassifier()
        imap = FakeImap(
            EmailUidBatch("44", (EmailFetchedMessage(uid=17, envelope=message),))
        )
        rules = FakeRuleClassifier(
            {message.message_id: rule("explicit_hard_ignore", positive=())}
        )

        await self.service(imap=imap, rules=rules, semantic=semantic).poll(NOW)

        self.assertEqual(semantic.calls, [])
        self.assertEqual(self.sent, [])
        record = self.store.find_by_alias("E-1000")
        self.assertEqual(record.delivery_state, "ignored")

    async def test_batches_semantic_classification_and_sends_only_redacted_summary(self):
        messages = (envelope(1), envelope(2))
        semantic = FakeSemanticClassifier()
        imap = FakeImap(
            EmailUidBatch(
                "44",
                tuple(
                    EmailFetchedMessage(uid=16 + index, envelope=message)
                    for index, message in enumerate(messages, 1)
                ),
            )
        )

        await self.service(imap=imap, semantic=semantic).poll(NOW)

        self.assertEqual(len(semantic.calls), 1)
        self.assertEqual(len(semantic.calls[0]), 2)
        self.assertEqual(len(self.sent), 2)
        for _, text, kwargs in self.sent:
            self.assertTrue(kwargs["redact_content"])
            self.assertNotIn("RAW PRIVATE SUBJECT", text)
            self.assertNotIn("RAW PRIVATE BODY", text)
            self.assertIn("相关度", text)
            self.assertIn("紧急性", text)

    async def test_model_failure_retries_from_archive_after_cursor_advanced(self):
        message = envelope(1)
        semantic = FakeSemanticClassifier(fail_once=True)
        imap = FakeImap(
            EmailUidBatch("44", (EmailFetchedMessage(uid=17, envelope=message),)),
            EmailUidBatch("44", ()),
        )
        service = self.service(imap=imap, semantic=semantic)

        with self.assertRaises(RuntimeError):
            await service.poll(NOW)
        self.assertEqual(self.store.cursor("INBOX").last_uid, 17)

        await service.poll(NOW + timedelta(minutes=5))

        self.assertEqual(len(semantic.calls), 2)
        self.assertEqual(self.store.find_by_alias("E-1000").classification.alias, "E-1000")

    async def test_uidvalidity_change_restarts_reading_from_uid_zero(self):
        self.store.reset_cursor("INBOX", "44")
        self.store.observe("INBOX", "44", 41, envelope(41))
        replacement = envelope(1)
        imap = FakeImap(
            EmailUidBatch("99", ()),
            EmailUidBatch("99", (EmailFetchedMessage(uid=1, envelope=replacement),)),
        )

        await self.service(imap=imap).poll(NOW)

        self.assertEqual(imap.calls, [(41, 100), (0, 100)])
        self.assertEqual(self.store.cursor("INBOX").uid_validity, "99")
        self.assertEqual(self.store.cursor("INBOX").last_uid, 1)

    async def test_failed_immediate_send_remains_pending_and_retries(self):
        message = envelope(1)
        imap = FakeImap(
            EmailUidBatch("44", (EmailFetchedMessage(uid=17, envelope=message),)),
            EmailUidBatch("44", ()),
        )
        self.send_results.extend(({"ok": False}, {"ok": True}))
        service = self.service(imap=imap)

        await service.poll(NOW)
        self.assertEqual(self.store.find_by_alias("E-1000").delivery_state, "pending")

        await service.poll(NOW + timedelta(minutes=5))

        self.assertEqual(len(self.sent), 2)
        self.assertEqual(self.store.find_by_alias("E-1000").delivery_state, "immediate_sent")

    async def test_shadow_mode_classifies_without_delivery(self):
        message = envelope(1)
        imap = FakeImap(
            EmailUidBatch("44", (EmailFetchedMessage(uid=17, envelope=message),))
        )

        await self.service(imap=imap, shadow_mode=True).poll(NOW)

        self.assertEqual(self.sent, [])
        self.assertEqual(self.store.find_by_alias("E-1000").delivery_state, "pending")

    async def test_semantic_low_value_is_marked_ignored(self):
        class LowValueSemantic(FakeSemanticClassifier):
            async def classify(self, candidates):
                self.calls.append(list(candidates))
                return tuple(
                    classification(alias, relevance=30, urgency="low", action="")
                    for alias, _, _ in candidates
                )

        message = envelope(1)
        imap = FakeImap(
            EmailUidBatch("44", (EmailFetchedMessage(uid=17, envelope=message),))
        )

        await self.service(imap=imap, semantic=LowValueSemantic()).poll(NOW)

        self.assertEqual(self.store.find_by_alias("E-1000").delivery_state, "ignored")

    async def test_digest_is_incremental_bounded_and_idempotent(self):
        for number in range(1, 12):
            record = self.store.observe("INBOX", "44", number, envelope(number))
            if number <= 4:
                item = classification(record.alias, relevance=90 - number, action="需要确认。")
            elif number <= 9:
                item = classification(
                    record.alias,
                    relevance=80 - number,
                    urgency="medium",
                    action="",
                )
            else:
                item = classification(
                    record.alias,
                    relevance=50,
                    urgency="low",
                    action="",
                )
            self.store.save_rule_decision(record.alias, rule())
            self.store.save_classification(record.alias, item)
        service = self.service()

        await service.run_digest(NOW, "12:30")

        self.assertEqual(len(self.sent), 1)
        _, text, kwargs = self.sent[0]
        self.assertTrue(kwargs["redact_content"])
        self.assertEqual(text.count("[E-"), 8)
        self.assertIn("Teacher 1", text)
        self.assertNotIn("RAW PRIVATE SUBJECT", text)
        self.assertNotIn("RAW PRIVATE BODY", text)
        self.assertTrue(self.store.was_digest_slot_sent("email_digest:2026-07-21:12:30"))

        await service.run_digest(NOW, "12:30")

        self.assertEqual(len(self.sent), 1)

    async def test_digest_marks_items_only_after_successful_send(self):
        record = self.store.observe("INBOX", "44", 1, envelope(1))
        self.store.save_rule_decision(record.alias, rule())
        self.store.save_classification(
            record.alias,
            classification(record.alias, relevance=70, urgency="medium", action=""),
        )
        self.send_results.extend(({"ok": False}, {"ok": True}))
        service = self.service()

        await service.run_digest(NOW, "20:30")
        self.assertEqual(self.store.find_by_alias(record.alias).delivery_state, "pending")

        await service.run_digest(NOW, "20:30")

        self.assertEqual(self.store.find_by_alias(record.alias).delivery_state, "digest_sent")
        self.assertEqual(len(self.sent), 2)

    async def test_empty_digest_sends_nothing(self):
        await self.service().run_digest(NOW, "12:30")

        self.assertEqual(self.sent, [])

    async def test_routing_thresholds_require_urgency_and_strong_positive_signal(self):
        from apps.qq_ai_bridge.services.email_automation_service import route_classification

        self.assertEqual(
            route_classification(classification("E-1000", relevance=80, urgency="high"), rule()),
            "immediate",
        )
        self.assertEqual(
            route_classification(
                classification("E-1000", relevance=80, urgency="medium", action=""),
                rule(),
            ),
            "digest",
        )
        self.assertEqual(
            route_classification(
                classification("E-1000", relevance=59, urgency="low", action=""),
                rule(),
            ),
            "possible",
        )
        self.assertEqual(
            route_classification(
                classification("E-1000", relevance=59, urgency="low", action=""),
                rule(positive=("direct_recipient",)),
            ),
            "ignore",
        )


if __name__ == "__main__":
    unittest.main()
