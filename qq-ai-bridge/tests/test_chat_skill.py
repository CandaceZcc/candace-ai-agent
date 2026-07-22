import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.skills.chat import ChatSkill


class ChatSkillTests(unittest.TestCase):
    def test_plain_email_mention_remains_available_to_chat_fallback(self):
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="private",
            user_id=1,
            self_id=2,
            group_id=None,
            group_config={},
            should_log=True,
            msg="我今天收到一封邮件，帮我看看",
            normalized_msg="我今天收到一封邮件，帮我看看",
            effective_text="我今天收到一封邮件，帮我看看",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
        )

        self.assertTrue(ChatSkill().can_handle(context))

    @patch("apps.qq_ai_bridge.skills.chat.group_strategy_decision")
    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text", return_value={"queued": True})
    def test_local_question_bypasses_probabilistic_strategy(self, mock_enqueue, mock_strategy):
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=3,
            group_config={"reply_all_messages": True, "bot_can_reply": True},
            should_log=True,
            msg="这个报错怎么解决？",
            normalized_msg="这个报错怎么解决？",
            effective_text="这个报错怎么解决？",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertTrue(result.response_payload["queue"]["queued"])
        mock_strategy.assert_not_called()
        self.assertEqual(mock_enqueue.call_args.kwargs["strategy"]["mode"], "text")

    @patch("apps.qq_ai_bridge.skills.chat.group_strategy_decision")
    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_stop_request_bypasses_strategy_and_stays_silent(self, mock_enqueue, mock_strategy):
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=3,
            group_config={"reply_all_messages": True, "bot_can_reply": True},
            should_log=True,
            msg="你别回复",
            normalized_msg="你别回复",
            effective_text="你别回复",
            mentioned_self=True,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertEqual(result.status, "ignore")
        self.assertEqual(result.response_payload["status"], "local_silence")
        mock_strategy.assert_not_called()
        mock_enqueue.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.chat.maybe_handle_private_admin_command", return_value=None)
    @patch("apps.qq_ai_bridge.skills.chat.enqueue_private_text", return_value={"queued": False, "reason": "runtime_busy"})
    def test_private_runtime_busy_returns_immediate_user_message(self, _mock_enqueue, _mock_admin):
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="private",
            user_id=1,
            self_id=2,
            group_id=None,
            group_config={},
            should_log=True,
            msg="你好",
            normalized_msg="你好",
            effective_text="你好",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertEqual(result.status, "busy")
        self.assertEqual(result.response_text, "当前消息较多，请稍后再试。")

    @patch("apps.qq_ai_bridge.skills.chat.group_strategy_decision")
    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text", return_value={"queued": False, "reason": "runtime_busy"})
    def test_explicit_group_runtime_busy_returns_immediate_user_message(self, _mock_enqueue, mock_strategy):
        mock_strategy.return_value = {"mode": "text", "reason": "explicit", "probabilities": {}}
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=3,
            group_config={"reply_all_messages": True, "bot_can_reply": True},
            should_log=True,
            msg="宝宝",
            normalized_msg="宝宝",
            effective_text="宝宝",
            mentioned_self=True,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertEqual(result.status, "busy")
        self.assertEqual(result.response_text, "当前消息较多，请稍后再试。")

    @patch("apps.qq_ai_bridge.skills.chat.maybe_handle_private_admin_command")
    def test_private_admin_command_bypasses_llm_queue(self, mock_admin):
        mock_admin.return_value = {"ok": True, "reply": "已更新：测试群", "group_id": "123"}
        context = SkillContext(
            data={"trace_id": "trace1"},
            post_type="message",
            message_type="private",
            user_id=273007866,
            self_id=2,
            group_id=None,
            group_config={},
            should_log=True,
            msg="查看测试群的策略",
            normalized_msg="查看测试群的策略",
            effective_text="查看测试群的策略",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertEqual(result.source, "private_admin_config")
        self.assertEqual(result.response_text, "已更新：测试群")

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_global_listen_group_does_not_mark_message_as_explicit_trigger(self, mock_enqueue):
        mock_enqueue.return_value = {"queued": True}
        logs = []
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=810938203,
            group_config={
                "reply_all_messages": True,
                "strategy": {"reply_probability": 1.0, "silence_probability": 0.0, "reaction_probability": 0.0},
            },
            should_log=True,
            msg="有个abi保护 不能随意启用功能",
            normalized_msg="有个abi保护 不能随意启用功能",
            effective_text="有个abi保护 不能随意启用功能",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=logs.append,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertTrue(result.handled)
        self.assertTrue(result.response_payload["queue"]["queued"])
        self.assertFalse(mock_enqueue.call_args.kwargs["explicit_trigger"])
        self.assertTrue(any("explicit_trigger=False" in item for item in logs))

    @patch("apps.qq_ai_bridge.skills.chat.group_strategy_decision")
    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_strategy_reaction_is_queued_instead_of_sent_immediately(
        self,
        mock_enqueue,
        mock_strategy,
    ):
        mock_strategy.return_value = {
            "mode": "reaction",
            "reason": "ambient_reply",
            "probabilities": {"reply": 0, "silence": 0, "reaction": 1},
        }
        mock_enqueue.return_value = {"queued": True}
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=810938203,
            group_config={"reply_all_messages": True, "bot_can_reply": True},
            should_log=True,
            msg="这个版本和之前感觉有些不一样",
            normalized_msg="这个版本和之前感觉有些不一样",
            effective_text="这个版本和之前感觉有些不一样",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertTrue(result.handled)
        self.assertTrue(mock_enqueue.called)
        self.assertEqual(result.response_payload["status"], "enqueued")

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_forwarded_private_context_is_not_queued_without_trigger(self, mock_enqueue):
        logs = []
        context = SkillContext(
            data={"message_id": 123, "trace_id": "trace1"},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=810938203,
            group_config={"reply_all_messages": True},
            should_log=True,
            msg="[聊天记录] Radioheadalism：查看哈基米音乐作者群的策略",
            normalized_msg="[聊天记录] Radioheadalism：查看哈基米音乐作者群的策略",
            effective_text="[聊天记录] Radioheadalism：查看哈基米音乐作者群的策略",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=logs.append,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_enqueue.assert_not_called()
        self.assertTrue(any("forwarded_private_context" in item for item in logs))

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_mention_marks_message_as_explicit_trigger(self, mock_enqueue):
        mock_enqueue.return_value = {"queued": True}
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=810938203,
            group_config={
                "reply_all_messages": True,
                "strategy": {"reply_probability": 1.0, "silence_probability": 0.0, "reaction_probability": 0.0},
            },
            should_log=True,
            msg="宝宝",
            normalized_msg="宝宝",
            effective_text="宝宝",
            mentioned_self=True,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        ChatSkill().handle(context)

        self.assertTrue(mock_enqueue.call_args.kwargs["explicit_trigger"])

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_bot_alias_marks_message_as_explicit_trigger(self, mock_enqueue):
        mock_enqueue.return_value = {"queued": True}
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=1041622553,
            group_config={
                "reply_all_messages": True,
                "strategy": {"reply_probability": 1.0, "silence_probability": 0.0, "reaction_probability": 0.0},
            },
            should_log=True,
            msg="这是机盖宁贴的爱心吗",
            normalized_msg="这是机盖宁贴的爱心吗",
            effective_text="这是机盖宁贴的爱心吗",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        ChatSkill().handle(context)

        self.assertTrue(mock_enqueue.call_args.kwargs["explicit_trigger"])

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_textual_second_machine_alias_marks_explicit_trigger(self, mock_enqueue):
        mock_enqueue.return_value = {"queued": True}
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=1041622553,
            group_config={"reply_all_messages": False},
            should_log=True,
            msg="@_Candace_二号机 电脑按win+r输入cmd然后在窗口输入shutdown /s /t 0",
            normalized_msg="@_Candace_二号机 电脑按win+r输入cmd然后在窗口输入shutdown /s /t 0",
            effective_text="@_Candace_二号机 电脑按win+r输入cmd然后在窗口输入shutdown /s /t 0",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        ChatSkill().handle(context)

        self.assertTrue(mock_enqueue.call_args.kwargs["explicit_trigger"])

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_owner_name_does_not_count_as_bot_alias(self, mock_enqueue):
        mock_enqueue.return_value = {"queued": True}
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=1041622553,
            group_config={
                "reply_all_messages": True,
                "strategy": {"reply_probability": 1.0, "silence_probability": 0.0, "reaction_probability": 0.0},
            },
            should_log=True,
            msg="candace 是谁",
            normalized_msg="candace 是谁",
            effective_text="candace 是谁",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        ChatSkill().handle(context)

        self.assertFalse(mock_enqueue.call_args.kwargs["explicit_trigger"])

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_mute_log_does_not_disable_reply_all_group_chat(self, mock_enqueue):
        mock_enqueue.return_value = {"queued": True}
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=810938203,
            group_config={
                "reply_all_messages": True,
                "mute_log": True,
                "bot_can_reply": True,
                "strategy": {"reply_probability": 1.0, "silence_probability": 0.0, "reaction_probability": 0.0},
            },
            should_log=False,
            msg="这个版本和之前感觉有些不一样",
            normalized_msg="这个版本和之前感觉有些不一样",
            effective_text="这个版本和之前感觉有些不一样",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertTrue(result.handled)
        self.assertTrue(mock_enqueue.called)

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_bot_can_reply_false_disables_group_chat_output(self, mock_enqueue):
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=810938203,
            group_config={"reply_all_messages": True, "bot_can_reply": False},
            should_log=True,
            msg="普通群聊",
            normalized_msg="普通群聊",
            effective_text="普通群聊",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_enqueue.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_group_message_at_other_user_is_ignored(self, mock_enqueue):
        logs = []
        context = SkillContext(
            data={"message_id": 123, "at_targets": ["999"]},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=810938203,
            group_config={"reply_all_messages": True},
            should_log=True,
            msg="在吗",
            normalized_msg="在吗",
            effective_text="在吗",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=logs.append,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_enqueue.assert_not_called()
        self.assertTrue(any("addressed_to_other" in item for item in logs))

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_group_reply_to_other_user_is_ignored(self, mock_enqueue):
        context = SkillContext(
            data={"message_id": 123, "reply_reference": {"message_id": "9988", "sender_id": "999"}},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=810938203,
            group_config={"reply_all_messages": True},
            should_log=True,
            msg="这个不对吧",
            normalized_msg="这个不对吧",
            effective_text="这个不对吧",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_enqueue.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_group_reply_to_bot_is_still_handled(self, mock_enqueue):
        mock_enqueue.return_value = {"queued": True}
        context = SkillContext(
            data={"message_id": 123, "reply_reference": {"message_id": "9988", "sender_id": "2"}},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=810938203,
            group_config={"reply_all_messages": True},
            should_log=True,
            msg="这个不对吧",
            normalized_msg="这个不对吧",
            effective_text="这个不对吧",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertTrue(result.handled)
        self.assertTrue(result.response_payload["queue"]["queued"])
        mock_enqueue.assert_called_once()

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    def test_group_mention_self_with_other_at_is_still_handled(self, mock_enqueue):
        mock_enqueue.return_value = {"queued": True}
        context = SkillContext(
            data={"message_id": 123, "at_targets": ["2", "999"]},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=810938203,
            group_config={"reply_all_messages": True},
            should_log=True,
            msg="你俩看看",
            normalized_msg="你俩看看",
            effective_text="你俩看看",
            mentioned_self=True,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertTrue(result.handled)
        self.assertTrue(result.response_payload["queue"]["queued"])
        mock_enqueue.assert_called_once()


if __name__ == "__main__":
    unittest.main()
