import sys
import unittest
from datetime import datetime, timezone

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.email_models import (
    EmailClassification,
    EmailEnvelope,
    EmailFetchedMessage,
    EmailRuleDecision,
    EmailUidSnapshot,
)


def envelope() -> EmailEnvelope:
    return EmailEnvelope(
        message_id="message-1",
        subject="Course update",
        sender="Teacher <teacher@example.invalid>",
        recipients=("student@example.invalid",),
        sent_at=datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc),
        body_text="The exam room changed.",
        attachments=(),
    )


class EmailAutomationModelTests(unittest.TestCase):
    def test_uid_snapshot_accepts_empty_mailbox_and_rejects_invalid_values(self):
        snapshot = EmailUidSnapshot(uid_validity="44", latest_uid=0)

        self.assertEqual(snapshot.latest_uid, 0)
        with self.assertRaises(ValueError):
            EmailUidSnapshot(uid_validity="", latest_uid=0)
        with self.assertRaises(ValueError):
            EmailUidSnapshot(uid_validity="44", latest_uid=-1)

    def test_fetched_message_requires_positive_uid(self):
        message = EmailFetchedMessage(uid=42, envelope=envelope())

        self.assertEqual(message.uid, 42)
        with self.assertRaises(ValueError):
            EmailFetchedMessage(uid=0, envelope=envelope())

    def test_rule_decision_validates_score_and_eligibility(self):
        decision = EmailRuleDecision(
            initial_score=70,
            eligibility="semantic_required",
            positive_signals=("direct_reply",),
            negative_signals=(),
        )

        self.assertEqual(decision.initial_score, 70)
        with self.assertRaises(ValueError):
            EmailRuleDecision(101, "semantic_required", (), ())
        with self.assertRaises(ValueError):
            EmailRuleDecision(50, "unknown", (), ())

    def test_classification_accepts_approved_contract(self):
        classification = EmailClassification(
            alias="E-1042",
            relevance_score=92,
            urgency="high",
            category="course_change",
            concise_title="课程考试安排调整",
            summary="考试时间发生变化。",
            action="今晚前确认。",
            deadline=None,
            reason="与你当前年级课程相关",
            confidence=0.94,
        )

        self.assertEqual(classification.relevance_score, 92)
        self.assertEqual(classification.urgency, "high")

    def test_classification_rejects_invalid_alias_scores_and_urgency(self):
        values = {
            "alias": "E-1042",
            "relevance_score": 92,
            "urgency": "high",
            "category": "course_change",
            "concise_title": "课程考试安排调整",
            "summary": "考试时间发生变化。",
            "action": "今晚前确认。",
            "deadline": None,
            "reason": "与你当前年级课程相关",
            "confidence": 0.94,
        }
        for key, invalid in (
            ("alias", "message-1"),
            ("relevance_score", -1),
            ("urgency", "soon"),
            ("confidence", 1.1),
        ):
            with self.subTest(key=key), self.assertRaises(ValueError):
                EmailClassification(**{**values, key: invalid})


if __name__ == "__main__":
    unittest.main()
