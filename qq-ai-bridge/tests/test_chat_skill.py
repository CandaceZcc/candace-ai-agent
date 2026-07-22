import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.barrage_6657_service import BarrageCandidate, BarrageMatchResult
from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.skills.chat import ChatSkill, _get_6657_group_lock


class ChatSkillTests(unittest.TestCase):
    @patch("apps.qq_ai_bridge.skills.chat.record_group_message_activity", create=True)
    @patch("apps.qq_ai_bridge.skills.chat.group_strategy_decision")
    def test_silenced_group_message_still_records_activity(self, mock_strategy, mock_record_activity):
        mock_strategy.return_value = {
            "mode": "silence",
            "reason": "cooldown",
            "delay_ms": 0,
            "probabilities": {},
            "cooldown_hit": True,
        }
        context = SkillContext(
            data={"message_id": 123}, post_type="message", message_type="group",
            user_id=1, self_id=2, group_id=3,
            group_config={"reply_all_messages": True, "bot_can_reply": True},
            should_log=True, msg="更正", normalized_msg="更正", effective_text="更正",
            mentioned_self=False, image_inputs={}, file_info=None,
            logger=lambda *_args: None, timestamp=10, nick="群友A",
        )

        result = ChatSkill().handle(context)

        self.assertEqual(result.status, "ignore")
        mock_record_activity.assert_called_once()

    def test_6657_group_lock_is_shared_only_within_one_group(self):
        self.assertIs(_get_6657_group_lock(1001), _get_6657_group_lock(1001))
        self.assertIsNot(_get_6657_group_lock(1001), _get_6657_group_lock(1002))

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text")
    @patch("apps.qq_ai_bridge.skills.chat.append_group_chat_log")
    @patch(
        "apps.qq_ai_bridge.skills.chat._load_recent_6657_context",
        return_value=["群友: 刚刚还在聊 NiKo 决赛"],
    )
    @patch("apps.qq_ai_bridge.skills.chat.send_group_msg_verbatim")
    @patch("apps.qq_ai_bridge.skills.chat.get_6657_matcher")
    def test_6657_match_sends_original_barrage_before_llm_queue(
        self,
        mock_get_matcher,
        mock_send_group_msg,
        mock_load_context,
        mock_append_log,
        mock_enqueue,
    ):
        candidate = BarrageCandidate(
            barrage_id=21943,
            text="6月22日 Niko：借一分 不管从哪借都行🙏\n\n7月20日 梅西：NiKo你做人真的可以",
            tags=("07", "28"),
            tag_labels=("NiKo", "足小子"),
            copy_count=74,
        )
        matcher = mock_get_matcher.return_value
        matcher.match.return_value = BarrageMatchResult(
            matched=True,
            reason="matched",
            candidate=candidate,
            confidence=0.91,
        )
        events = []
        matcher.store.record_send.side_effect = lambda **_kwargs: events.append("record") or 42
        mock_send_group_msg.side_effect = (
            lambda *_args, **_kwargs: events.append("send") or {"ok": True}
        )
        mock_append_log.side_effect = OSError("chat log unavailable")
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=810938203,
            group_config={
                "reply_all_messages": True,
                "bot_can_reply": True,
                "enable_6657_barrage": True,
                "capture_all_messages": True,
            },
            should_log=True,
            msg="NiKo这个冠军是不是又借的",
            normalized_msg="NiKo这个冠军是不是又借的",
            effective_text="NiKo这个冠军是不是又借的",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertTrue(result.handled)
        self.assertEqual(result.source, "6657_barrage")
        self.assertEqual(result.response_payload["status"], "sent")
        mock_send_group_msg.assert_called_once_with(810938203, candidate.text, quiet=False)
        mock_load_context.assert_called_once_with(810938203, limit=5)
        matcher.match.assert_called_once_with(
            "NiKo这个冠军是不是又借的",
            ["群友: 刚刚还在聊 NiKo 决赛"],
            context.group_config,
            group_id=810938203,
            now=10,
        )
        matcher.store.record_send.assert_called_once_with(
            group_id=810938203,
            candidate=candidate,
            confidence=0.91,
            now=10,
        )
        self.assertEqual(events, ["record", "send"])
        matcher.store.delete_send.assert_not_called()
        mock_append_log.assert_called_once()
        timeline_entry = mock_append_log.call_args.args[2]
        self.assertEqual(timeline_entry.get("role"), "assistant")
        self.assertEqual(timeline_entry["assistant"], candidate.text)
        self.assertNotIn("message", timeline_entry)
        mock_enqueue.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text", return_value={"queued": True})
    @patch("apps.qq_ai_bridge.skills.chat.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.chat._load_recent_6657_context", return_value=[])
    @patch("apps.qq_ai_bridge.skills.chat.send_group_msg_verbatim", return_value={"ok": False})
    @patch("apps.qq_ai_bridge.skills.chat.get_6657_matcher")
    def test_6657_send_failure_falls_back_to_llm_queue(
        self,
        mock_get_matcher,
        _mock_send_group_msg,
        _mock_load_context,
        mock_append_log,
        mock_enqueue,
    ):
        candidate = BarrageCandidate(
            barrage_id=1,
            text="原弹幕",
            tags=("07",),
            tag_labels=("NiKo",),
            copy_count=10,
        )
        matcher = mock_get_matcher.return_value
        matcher.match.return_value = BarrageMatchResult(
            matched=True,
            reason="matched",
            candidate=candidate,
            confidence=0.9,
        )
        matcher.store.record_send.return_value = 42
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=3,
            group_config={
                "reply_all_messages": True,
                "bot_can_reply": True,
                "enable_6657_barrage": True,
            },
            should_log=True,
            msg="NiKo这个冠军是不是又借的？",
            normalized_msg="NiKo这个冠军是不是又借的？",
            effective_text="NiKo这个冠军是不是又借的？",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertEqual(result.source, "chat")
        self.assertTrue(mock_enqueue.called)
        matcher.store.record_send.assert_called_once()
        matcher.store.delete_send.assert_called_once_with(send_log_id=42)
        mock_append_log.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text", return_value={"queued": True})
    @patch("apps.qq_ai_bridge.skills.chat.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.chat._load_recent_6657_context", return_value=[])
    @patch("apps.qq_ai_bridge.skills.chat.send_group_msg_verbatim", return_value={"ok": True})
    @patch("apps.qq_ai_bridge.skills.chat.get_6657_matcher")
    def test_6657_record_failure_does_not_send_and_falls_back_to_llm_queue(
        self,
        mock_get_matcher,
        mock_send_group_msg,
        _mock_load_context,
        mock_append_log,
        mock_enqueue,
    ):
        candidate = BarrageCandidate(
            barrage_id=1,
            text="原弹幕",
            tags=("07",),
            tag_labels=("NiKo",),
            copy_count=10,
        )
        matcher = mock_get_matcher.return_value
        matcher.match.return_value = BarrageMatchResult(
            matched=True,
            reason="matched",
            candidate=candidate,
            confidence=0.9,
        )
        matcher.store.record_send.side_effect = OSError("sqlite unavailable")
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=3,
            group_config={
                "reply_all_messages": True,
                "bot_can_reply": True,
                "enable_6657_barrage": True,
            },
            should_log=True,
            msg="NiKo这个冠军是不是又借的？",
            normalized_msg="NiKo这个冠军是不是又借的？",
            effective_text="NiKo这个冠军是不是又借的？",
            mentioned_self=False,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        result = ChatSkill().handle(context)

        self.assertEqual(result.source, "chat")
        self.assertTrue(mock_enqueue.called)
        mock_send_group_msg.assert_not_called()
        mock_append_log.assert_not_called()

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
