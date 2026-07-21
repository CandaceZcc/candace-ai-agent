import asyncio
import sys
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.email_models import EmailDigest
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
        self.submit = MagicMock(return_value=object())
        self.factory = MagicMock()
        self.send = MagicMock(return_value={"ok": True})
        self.run_async = MagicMock(side_effect=asyncio.run)

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
        self.send.assert_called_once_with(42, "final digest", quiet=True)


if __name__ == "__main__":
    unittest.main()
