import stat
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.email_models import (
    EmailClassification,
    EmailEnvelope,
    EmailRuleDecision,
)
from apps.qq_ai_bridge.services.email_processing_store import EmailProcessingStore

NOW = datetime(2026, 7, 21, 12, 0, tzinfo=timezone.utc)


def envelope(number: int = 1, *, sent_at: datetime | None = NOW) -> EmailEnvelope:
    return EmailEnvelope(
        message_id=f"message-{number}",
        subject=f"Private subject {number}",
        sender=f"Teacher {number} <teacher{number}@example.invalid>",
        recipients=("student@example.invalid",),
        sent_at=sent_at,
        body_text=f"Private body {number}",
        attachments=(),
    )


def classification(alias: str, relevance: int = 80) -> EmailClassification:
    return EmailClassification(
        alias=alias,
        relevance_score=relevance,
        urgency="medium",
        category="research",
        concise_title="科研项目更新",
        summary="项目安排已更新。",
        action="查看安排。",
        deadline=None,
        reason="与你的专业相关",
        confidence=0.9,
    )


class EmailProcessingStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.path = Path(self.temp_dir.name) / "automation-state.json"
        self.store = EmailProcessingStore(self.path, now=lambda: NOW)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_observe_assigns_stable_alias_and_advances_cursor(self):
        first = self.store.observe("INBOX", "44", 17, envelope())
        duplicate = self.store.observe("INBOX", "44", 19, envelope())

        self.assertRegex(first.alias, r"^E-\d{4,}$")
        self.assertEqual(duplicate.alias, first.alias)
        self.assertEqual(self.store.cursor("INBOX").uid_validity, "44")
        self.assertEqual(self.store.cursor("INBOX").last_uid, 19)

    def test_state_file_is_private_and_contains_no_raw_mail(self):
        self.store.observe("INBOX", "44", 17, envelope())

        state_text = self.path.read_text(encoding="utf-8")
        self.assertEqual(stat.S_IMODE(self.path.stat().st_mode), 0o600)
        self.assertNotIn("Private subject", state_text)
        self.assertNotIn("Private body", state_text)
        self.assertNotIn("teacher1@example.invalid", state_text)
        self.assertIn("Teacher 1", state_text)

    def test_restart_reloads_alias_and_cursor(self):
        observed = self.store.observe("INBOX", "44", 17, envelope())

        restarted = EmailProcessingStore(self.path, now=lambda: NOW)

        self.assertEqual(restarted.find_by_alias(observed.alias), observed)
        self.assertEqual(restarted.cursor("INBOX").last_uid, 17)

    def test_uidvalidity_reset_clears_cursor_without_forgetting_messages(self):
        observed = self.store.observe("INBOX", "44", 17, envelope())

        self.store.reset_cursor("INBOX", "99")

        self.assertEqual(self.store.cursor("INBOX").uid_validity, "99")
        self.assertEqual(self.store.cursor("INBOX").last_uid, 0)
        self.assertIsNotNone(self.store.find_by_alias(observed.alias))

    def test_rule_and_model_decisions_survive_restart(self):
        observed = self.store.observe("INBOX", "44", 17, envelope())
        rule = EmailRuleDecision(75, "semantic_required", ("interest:cst",), ())
        self.store.save_rule_decision(observed.alias, rule)
        self.store.save_classification(observed.alias, classification(observed.alias))

        restarted = EmailProcessingStore(self.path, now=lambda: NOW)
        record = restarted.find_by_alias(observed.alias)

        self.assertEqual(record.rule_decision, rule)
        self.assertEqual(record.classification, classification(observed.alias))
        self.assertEqual(record.delivery_state, "pending")

    def test_pending_analysis_returns_only_unclassified_semantic_records(self):
        pending = self.store.observe("INBOX", "44", 17, envelope(1))
        classified = self.store.observe("INBOX", "44", 18, envelope(2))
        low_value = self.store.observe("INBOX", "44", 19, envelope(3))
        semantic_rule = EmailRuleDecision(75, "semantic_required", ("interest:cst",), ())
        self.store.save_rule_decision(pending.alias, semantic_rule)
        self.store.save_rule_decision(classified.alias, semantic_rule)
        self.store.save_classification(classified.alias, classification(classified.alias))
        self.store.save_rule_decision(
            low_value.alias,
            EmailRuleDecision(20, "deterministic_low_value", (), ("routine_event",)),
        )

        records = self.store.pending_analysis(limit=100)

        self.assertEqual([record.alias for record in records], [pending.alias])

    def test_pending_digest_filters_by_time_relevance_and_delivery(self):
        recent = self.store.observe("INBOX", "44", 17, envelope(1))
        old = self.store.observe(
            "INBOX",
            "44",
            18,
            envelope(2, sent_at=NOW - timedelta(hours=25)),
        )
        immediate = self.store.observe("INBOX", "44", 19, envelope(3))
        low = self.store.observe("INBOX", "44", 20, envelope(4))
        for record, relevance in ((recent, 80), (old, 80), (immediate, 90), (low, 30)):
            self.store.save_classification(record.alias, classification(record.alias, relevance))
        self.store.mark_immediate_sent(immediate.alias, NOW)

        pending = self.store.pending_digest(NOW, lookback_hours=24)

        self.assertEqual([record.alias for record in pending], [recent.alias])

    def test_digest_is_marked_only_for_selected_aliases_and_slot(self):
        first = self.store.observe("INBOX", "44", 17, envelope(1))
        second = self.store.observe("INBOX", "44", 18, envelope(2))
        for record in (first, second):
            self.store.save_classification(record.alias, classification(record.alias))
        slot = "email_digest:2026-07-21T12:30+08:00"

        self.store.mark_digest_sent((first.alias,), slot, NOW)

        self.assertTrue(self.store.was_digest_slot_sent(slot))
        self.assertEqual(self.store.find_by_alias(first.alias).delivery_state, "digest_sent")
        self.assertEqual(self.store.find_by_alias(second.alias).delivery_state, "pending")

    def test_mark_ignored_removes_message_from_pending_digest(self):
        observed = self.store.observe("INBOX", "44", 17, envelope())
        self.store.save_classification(observed.alias, classification(observed.alias))

        self.store.mark_ignored(observed.alias, "low_value")

        self.assertEqual(self.store.pending_digest(NOW), ())
        self.assertEqual(self.store.find_by_alias(observed.alias).delivery_state, "ignored")


if __name__ == "__main__":
    unittest.main()
