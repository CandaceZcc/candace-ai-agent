import sys
import unittest
from dataclasses import replace
from datetime import datetime, timezone

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.email_models import EmailEnvelope
from apps.qq_ai_bridge.services.email_preference_service import EmailPreferenceProfile
from apps.qq_ai_bridge.services.email_rule_classifier import EmailRuleClassifier


def profile(**overrides) -> EmailPreferenceProfile:
    values = {
        "profile_version": 1,
        "watched_senders": (),
        "ignored_senders": (),
        "watched_domains": (),
        "ignored_domains": (),
        "positive_terms": (),
        "negative_terms": ("campus recruitment", "招聘会"),
        "interest_terms": ("computer science", "cst", "robotics", "embedded", "机器人"),
        "cohort_terms": ("year 3", "大三", "2024级"),
        "hard_ignore_rules": (),
        "manual_adjustments": (),
        "learned_adjustments": (),
    }
    values.update(overrides)
    return EmailPreferenceProfile(**values)


def envelope(
    *,
    subject: str,
    body: str = "",
    sender: str = "Office <office@school.example.invalid>",
    recipients: tuple[str, ...] = ("student@school.example.invalid",),
) -> EmailEnvelope:
    return EmailEnvelope(
        message_id="message-1",
        subject=subject,
        sender=sender,
        recipients=recipients,
        sent_at=datetime(2026, 7, 21, 9, 0, tzinfo=timezone.utc),
        body_text=body,
        attachments=(),
    )


class EmailRuleClassifierTests(unittest.TestCase):
    def setUp(self):
        self.classifier = EmailRuleClassifier(owner_address="student@school.example.invalid")

    def test_direct_reply_and_recipient_require_semantic_review(self):
        decision = self.classifier.classify(
            envelope(
                subject="Re: course exam change",
                sender="Teacher <teacher@gmail.com>",
            ),
            profile(),
        )

        self.assertEqual(decision.eligibility, "semantic_required")
        self.assertIn("direct_reply", decision.positive_signals)
        self.assertIn("direct_recipient", decision.positive_signals)
        self.assertGreaterEqual(decision.initial_score, 60)

    def test_reply_score_does_not_depend_on_edu_or_external_domain(self):
        school_reply = self.classifier.classify(
            envelope(
                subject="Re: course exam change",
                sender="Teacher <teacher@school.example.invalid>",
            ),
            profile(),
        )
        external_reply = self.classifier.classify(
            envelope(
                subject="Re: course exam change",
                sender="Teacher <teacher@gmail.com>",
            ),
            profile(),
        )

        self.assertEqual(school_reply.initial_score, external_reply.initial_score)
        self.assertNotIn("personal_sender", school_reply.positive_signals)
        self.assertNotIn("personal_sender", external_reply.positive_signals)

    def test_reply_chain_inside_body_is_a_positive_signal(self):
        decision = self.classifier.classify(
            envelope(
                subject="Exam arrangement",
                body="Please confirm.\nFrom: Student\nEarlier thread content",
                sender="Teacher <teacher@school.example.invalid>",
            ),
            profile(),
        )

        self.assertIn("reply_thread", decision.positive_signals)
        self.assertEqual(decision.eligibility, "semantic_required")

    def test_course_code_in_subject_is_a_positive_signal(self):
        decision = self.classifier.classify(
            envelope(subject="CST2040 tutorial arrangement"),
            profile(),
        )

        self.assertIn("course_code", decision.positive_signals)

    def test_broad_recipient_scope_is_a_weak_signal_that_still_reaches_model(self):
        decision = self.classifier.classify(
            envelope(
                subject="Faculty information update",
                recipients=("all-students@school.example.invalid",),
            ),
            profile(),
        )

        self.assertIn("broad_recipient", decision.negative_signals)
        self.assertEqual(decision.eligibility, "semantic_required")

    def test_cohort_and_interest_terms_raise_relevance(self):
        decision = self.classifier.classify(
            envelope(subject="Year 3 CST robotics research opportunity"),
            profile(),
        )

        self.assertEqual(decision.eligibility, "semantic_required")
        self.assertTrue(any(item.startswith("interest:") for item in decision.positive_signals))
        self.assertTrue(any(item.startswith("cohort:") for item in decision.positive_signals))
        self.assertGreaterEqual(decision.initial_score, 70)

    def test_exam_and_course_action_is_a_positive_signal(self):
        decision = self.classifier.classify(
            envelope(subject="Course exam room changed", body="Please confirm before tonight."),
            profile(),
        )

        self.assertIn("academic_action", decision.positive_signals)
        self.assertEqual(decision.eligibility, "semantic_required")

    def test_research_and_competition_are_positive_when_technical(self):
        decision = self.classifier.classify(
            envelope(subject="计算机机器人科研竞赛通知"),
            profile(),
        )

        self.assertIn("research_competition", decision.positive_signals)
        self.assertTrue(any(item.startswith("interest:") for item in decision.positive_signals))

    def test_generic_recruiting_without_positive_signal_is_low_value(self):
        decision = self.classifier.classify(
            envelope(
                subject="Campus recruitment and generic internship fair",
                recipients=("all-students@school.example.invalid",),
            ),
            profile(),
        )

        self.assertEqual(decision.eligibility, "deterministic_low_value")
        self.assertIn("generic_recruiting", decision.negative_signals)
        self.assertLessEqual(decision.initial_score, 20)

    def test_direct_address_does_not_rescue_generic_recruiting(self):
        decision = self.classifier.classify(
            envelope(subject="Campus recruitment and generic internship fair"),
            profile(),
        )

        self.assertEqual(decision.eligibility, "deterministic_low_value")
        self.assertNotIn("direct_recipient", decision.positive_signals)

    def test_technical_recruiting_positive_signal_overrides_generic_penalty(self):
        decision = self.classifier.classify(
            envelope(subject="Campus recruitment for embedded robotics Year 3 students"),
            profile(),
        )

        self.assertEqual(decision.eligibility, "semantic_required")
        self.assertTrue(decision.positive_signals)
        self.assertIn("generic_recruiting", decision.negative_signals)

    def test_routine_mass_event_without_positive_signal_is_low_value(self):
        decision = self.classifier.classify(
            envelope(
                subject="Weekly campus activity newsletter",
                body="This message was sent to the all students mailing list. Unsubscribe here.",
                recipients=("all-students@school.example.invalid",),
            ),
            profile(),
        )

        self.assertEqual(decision.eligibility, "deterministic_low_value")
        self.assertIn("routine_event", decision.negative_signals)
        self.assertIn("mass_mail", decision.negative_signals)

    def test_mass_mail_signal_alone_still_requires_semantic_review(self):
        decision = self.classifier.classify(
            envelope(
                subject="Faculty opportunity announcement",
                body="Dear students, this message was sent to the all students mailing list.",
                recipients=("all-students@school.example.invalid",),
            ),
            profile(),
        )

        self.assertEqual(decision.eligibility, "semantic_required")
        self.assertEqual(decision.positive_signals, ())
        self.assertEqual(decision.negative_signals, ("mass_mail",))

    def test_explicit_ignored_sender_is_a_hard_ignore(self):
        decision = self.classifier.classify(
            envelope(subject="CST exam change", sender="Ignored <ignored@example.invalid>"),
            replace(profile(), ignored_senders=("ignored@example.invalid",)),
        )

        self.assertEqual(decision.eligibility, "explicit_hard_ignore")
        self.assertEqual(decision.positive_signals, ())

    def test_manual_hard_ignore_phrase_has_highest_precedence(self):
        decision = self.classifier.classify(
            envelope(subject="CST robotics weekly digest"),
            replace(profile(), hard_ignore_rules=("weekly digest",)),
        )

        self.assertEqual(decision.eligibility, "explicit_hard_ignore")

    def test_profile_adjustment_is_applied_but_score_remains_bounded(self):
        adjusted = replace(
            profile(),
            manual_adjustments=(("category:research", 20), ("domain:school.example.invalid", 20)),
        )
        decision = self.classifier.classify(
            envelope(subject="Research update"),
            adjusted,
        )

        self.assertLessEqual(decision.initial_score, 100)
        self.assertIn("profile_adjustment:domain", decision.positive_signals)


if __name__ == "__main__":
    unittest.main()
