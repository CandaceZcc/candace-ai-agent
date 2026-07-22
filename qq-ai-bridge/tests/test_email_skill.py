import asyncio
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.email_archive_service import EmailArchiveService
from apps.qq_ai_bridge.services.email_models import (
    EmailClassification,
    EmailDigest,
    EmailEnvelope,
    EmailRuleDecision,
)
from apps.qq_ai_bridge.services.email_preference_service import EmailPreferenceStore
from apps.qq_ai_bridge.services.email_processing_store import EmailProcessingStore
from apps.qq_ai_bridge.services.time_utils import LOCAL_TIMEZONE
from apps.qq_ai_bridge.skills.base import SkillContext


def context(
    text: str,
    *,
    user_id: int = 42,
    message_type: str = "private",
) -> SkillContext:
    return SkillContext(
        data={"message_id": 998877},
        post_type="message",
        message_type=message_type,
        user_id=user_id,
        self_id=10000,
        group_id=12345 if message_type == "group" else None,
        group_config={"bot_can_reply": True},
        should_log=True,
        msg=text,
        normalized_msg=text,
        effective_text=text,
        mentioned_self=False,
        image_inputs={},
        file_info=None,
        logger=lambda *_args, **_kwargs: None,
        timestamp=123,
        message_id=998877,
        nick="tester",
        raw_message=text,
    )


class EmailSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        root = Path(self.temp_dir.name)
        self.submit = MagicMock(return_value=object())
        self.factory = MagicMock()
        self.send = MagicMock(return_value={"ok": True})
        self.run_async = MagicMock(side_effect=asyncio.run)
        self.archive = EmailArchiveService(root / "email")
        self.processing = EmailProcessingStore(root / "automation-state.json")
        self.preferences = EmailPreferenceStore(
            root / "profile.json",
            root / "learned-feedback.json",
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def skill(self, **overrides):
        from apps.qq_ai_bridge.skills.email import EmailSkill

        values = {
            "enabled": True,
            "owner_qq": 42,
            "submit_task": self.submit,
            "digest_service_factory": self.factory,
            "send_private": self.send,
            "run_async": self.run_async,
            "provider_name": "responses_proxy",
            "model_name": "gpt-5.6-terra",
            "now": lambda: datetime(2026, 7, 22, 10, 0, tzinfo=LOCAL_TIMEZONE),
            "archive_service": self.archive,
            "processing_store": self.processing,
            "preference_store": self.preferences,
        }
        values.update(overrides)
        return EmailSkill(**values)

    def test_registry_places_email_before_chat(self):
        from apps.qq_ai_bridge.skills.registry import build_skill_registry

        names = [skill.name for skill in build_skill_registry()]

        self.assertLess(names.index("email"), names.index("chat"))

    def test_disabled_feature_does_not_match(self):
        self.assertFalse(self.skill(enabled=False).can_handle(context("邮件 今天")))

    def test_non_owner_private_user_is_rejected(self):
        self.assertFalse(self.skill().can_handle(context("邮件 今天", user_id=7)))

    def test_group_message_does_not_match(self):
        self.assertFalse(self.skill().can_handle(context("邮件 今天", message_type="group")))

    def test_feedback_is_rejected_for_non_owner_and_group(self):
        self.assertFalse(self.skill().can_handle(context("邮件 E-1042 有用", user_id=7)))
        self.assertFalse(
            self.skill().can_handle(context("邮件 E-1042 有用", message_type="group"))
        )

    def test_explicit_command_is_enqueued(self):
        result = self.skill().handle(context("邮件 最近 7 天"))

        self.assertEqual(result.status, "queued")
        self.assertIn("正在读取", result.response_text)
        self.submit.assert_called_once()
        self.factory.assert_not_called()
        worker, user_id, command = self.submit.call_args.args
        self.assertTrue(callable(worker))
        self.assertEqual(user_id, 42)
        self.assertEqual(command.period_label, "最近 7 天")

    def test_status_does_not_contact_imap(self):
        result = self.skill().handle(context("邮件 状态"))

        self.assertEqual(result.status, "status")
        self.assertIn("responses_proxy", result.response_text)
        self.assertIn("gpt-5.6-terra", result.response_text)
        self.assertNotIn("password", result.response_text.lower())
        self.factory.assert_not_called()
        self.submit.assert_not_called()

    def test_help_is_deterministic(self):
        first = self.skill().handle(context("邮件 帮助"))
        second = self.skill().handle(context("邮件 帮助"))

        self.assertEqual(first.response_text, second.response_text)
        self.assertIn("邮件 最近 N 天", first.response_text)
        self.submit.assert_not_called()

    def test_invalid_email_subcommand_returns_help(self):
        result = self.skill().handle(context("邮件 随便看看"))

        self.assertEqual(result.status, "invalid")
        self.assertIn("邮件 今天", result.response_text)
        self.assertIn("邮件 上周", result.response_text)

    def test_plain_chat_containing_email_word_falls_through(self):
        self.assertFalse(self.skill().can_handle(context("我今天收到一封邮件，帮我看看")))

    def test_feedback_resolves_alias_and_persists_private_signals(self):
        processing = MagicMock()
        processing.find_by_alias.return_value = SimpleNamespace(
            alias="E-1042",
            message_hash="a" * 64,
            classification=SimpleNamespace(category="course_change"),
            rule_decision=SimpleNamespace(positive_signals=("interest:robotics",)),
        )
        archive = MagicMock()
        archive.load_envelope.return_value = SimpleNamespace(
            sender="Teacher Name <teacher@example.invalid>"
        )
        preferences = MagicMock()

        result = self.skill(
            processing_store=processing,
            archive_service=archive,
            preference_store=preferences,
        ).handle(context("邮件 E-1042 关注发件人"))

        preferences.apply_feedback.assert_called_once_with(
            "E-1042",
            "watch_sender",
            {"sender": "teacher@example.invalid"},
        )
        self.assertEqual(result.status, "feedback")
        self.assertIn("E-1042", result.response_text)
        self.assertNotIn("teacher@example.invalid", result.response_text)
        self.submit.assert_not_called()

    def test_feedback_not_found_and_undo_are_deterministic(self):
        processing = MagicMock()
        preferences = MagicMock()
        processing.find_by_alias.return_value = None
        skill = self.skill(processing_store=processing, preference_store=preferences)

        missing = skill.handle(context("邮件 E-9999 有用"))
        self.assertEqual(missing.status, "feedback_not_found")
        self.assertIn("可能已过期", missing.response_text)
        preferences.apply_feedback.assert_not_called()

        processing.find_by_alias.return_value = SimpleNamespace(alias="E-1042")
        preferences.undo_feedback.return_value = True
        undone = skill.handle(context("邮件 E-1042 撤销反馈"))
        self.assertEqual(undone.status, "feedback")
        self.assertIn("已撤销", undone.response_text)

    def test_preferences_summary_is_synchronous_and_redacted(self):
        preferences = MagicMock()
        preferences.summary.return_value = "邮件偏好版本：1\n已学习反馈：2"

        result = self.skill(preference_store=preferences).handle(context("邮件 偏好"))

        self.assertEqual(result.status, "preferences")
        self.assertEqual(result.response_text, "邮件偏好版本：1\n已学习反馈：2")
        preferences.summary.assert_called_once_with()
        self.submit.assert_not_called()

    def test_queue_full_returns_busy_without_starting_work(self):
        result = self.skill(submit_task=MagicMock(return_value=None)).handle(context("邮件 今天"))

        self.assertEqual(result.status, "busy")
        self.assertIn("任务较多", result.response_text)
        self.factory.assert_not_called()
        self.send.assert_not_called()

    def test_worker_sends_final_digest_once(self):
        digest = EmailDigest("今天", 1, "final digest", ("message-1",), False)
        service = SimpleNamespace(build_digest=AsyncMock(return_value=digest))
        self.factory.return_value = service
        skill = self.skill()
        skill.handle(context("邮件 今天"))
        worker, user_id, command = self.submit.call_args.args

        worker(user_id, command)

        service.build_digest.assert_awaited_once_with(command.query, period_label="今天")
        self.run_async.assert_called_once()
        self.send.assert_called_once_with(
            42,
            "final digest",
            quiet=True,
            redact_content=True,
        )

    def test_worker_error_message_uses_redacted_delivery(self):
        service = SimpleNamespace(build_digest=AsyncMock(side_effect=RuntimeError("private body")))
        self.factory.return_value = service
        skill = self.skill()
        skill.handle(context("邮件 今天"))
        worker, user_id, command = self.submit.call_args.args

        worker(user_id, command)

        self.send.assert_called_once_with(
            42,
            "邮件摘要生成失败，稍后再试。",
            quiet=True,
            redact_content=True,
        )

    def test_feedback_updates_private_preferences_without_queuing(self):
        alias = self._archive_classified_email()

        result = self.skill().handle(context(f"邮件 {alias} 有用"))

        self.assertEqual(result.status, "feedback")
        self.assertIn(alias, result.response_text)
        self.assertNotIn("Teacher", result.response_text)
        self.assertNotIn("teacher@example.invalid", result.response_text)
        self.assertEqual(
            self.preferences.load().score_for("sender:teacher@example.invalid"),
            5,
        )
        self.submit.assert_not_called()

    def test_watch_sender_learns_exact_sender_not_shared_domain(self):
        alias = self._archive_classified_email()

        self.skill().handle(context(f"邮件 {alias} 关注发件人"))

        profile = self.preferences.load()
        self.assertEqual(profile.score_for("sender:teacher@example.invalid"), 15)
        self.assertEqual(profile.score_for("domain:example.invalid"), 0)

    def test_feedback_can_be_undone(self):
        alias = self._archive_classified_email()
        skill = self.skill()
        skill.handle(context(f"邮件 {alias} 忽略此类"))

        result = skill.handle(context(f"邮件 {alias} 撤销反馈"))

        self.assertEqual(result.status, "feedback")
        self.assertIn("已撤销", result.response_text)
        self.assertEqual(
            self.preferences.load().score_for("sender:teacher@example.invalid"),
            0,
        )

    def test_preferences_returns_redacted_summary(self):
        result = self.skill().handle(context("邮件 偏好"))

        self.assertEqual(result.status, "preferences")
        self.assertIn("邮件偏好版本", result.response_text)
        self.assertNotIn("example.invalid", result.response_text)
        self.submit.assert_not_called()

    def test_feedback_unknown_alias_has_deterministic_response(self):
        result = self.skill().handle(context("邮件 E-9999 忽略"))

        self.assertEqual(result.status, "feedback_not_found")
        self.assertEqual(result.response_text, "未找到邮件编号 E-9999，可能已过期。")

    def test_feedback_remains_owner_private(self):
        self.assertFalse(self.skill().can_handle(context("邮件 E-1042 有用", user_id=7)))
        self.assertFalse(
            self.skill().can_handle(context("邮件 E-1042 有用", message_type="group"))
        )

    def _archive_classified_email(self) -> str:
        envelope = EmailEnvelope(
            message_id="<feedback@example.invalid>",
            subject="Private course update",
            sender="Teacher <teacher@example.invalid>",
            recipients=("student@example.invalid",),
            sent_at=datetime(2026, 7, 22, 9, 0, tzinfo=timezone.utc),
            body_text="Private body",
            attachments=(),
        )
        self.archive.archive_envelope(envelope)
        record = self.processing.observe("INBOX", "44", 17, envelope)
        self.processing.save_rule_decision(
            record.alias,
            EmailRuleDecision(80, "semantic_required", ("course_code",), ()),
        )
        self.processing.save_classification(
            record.alias,
            EmailClassification(
                alias=record.alias,
                relevance_score=85,
                urgency="high",
                category="course_change",
                concise_title="课程安排更新",
                summary="课程安排有变化。",
                action="查看新安排。",
                deadline=None,
                reason="与你的课程相关",
                confidence=0.9,
            ),
        )
        return record.alias


if __name__ == "__main__":
    unittest.main()
