import sys
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services import group_chat_service
from apps.qq_ai_bridge.services.group_chat_service import (
    PendingGroupMessage,
    _GROUP_CHAT_STATES,
    _RECENT_REPEAT_FOLLOWS,
    _claim_repeat_follow,
    _get_group_chat_state,
    _decide_group_response_mode_with_llm,
    _detect_direct_reaction_request_count,
    _detect_repeat_follow_text,
    _detect_requested_parts,
    _compute_turn_extension_ms,
    enqueue_group_text,
    _get_reaction_decision_mode,
    _humanize_group_reply,
    _pick_text_reply_target_message_id,
    _pick_reaction_target_message_id,
    _parse_group_response_mode,
    _extract_emoji_tag,
    _build_explicit_trigger_no_reply_fallback,
    _is_global_listen_group,
    _should_silence_trivial_global_message,
    _should_use_reaction_instead,
)
from apps.qq_ai_bridge.services.response_action import ActionKind, ResponseAction


class GroupChatServiceTests(unittest.TestCase):
    def setUp(self):
        _GROUP_CHAT_STATES.clear()
        _RECENT_REPEAT_FOLLOWS.clear()

    def test_detect_requested_parts_in_chinese(self):
        self.assertEqual(_detect_requested_parts("我叫你发两条消息"), 2)
        self.assertEqual(_detect_requested_parts("分三条回我"), 3)

    def test_detect_requested_parts_in_digits(self):
        self.assertEqual(_detect_requested_parts("发2条"), 2)
        self.assertEqual(_detect_requested_parts("发 4 条回复"), 4)

    def test_detect_requested_parts_ignores_non_multi_requests(self):
        self.assertIsNone(_detect_requested_parts("随便说一句"))
        self.assertIsNone(_detect_requested_parts("发一条消息"))

    def test_humanize_group_reply_reduces_template_fillers(self):
        self.assertEqual(_humanize_group_reply("确实 贴贴", "你们在聊什么"), "收到")
        self.assertEqual(_humanize_group_reply("草 草 草", "你们在聊什么"), "收到")
        self.assertEqual(
            _humanize_group_reply("发什么类型？文字、图片还是表情？", "随便发点什么"),
            "发啥都行，我看着接。",
        )
        self.assertEqual(
            _humanize_group_reply("Linux 原生性能更好，没有 WSL 的虚拟化开销，适合性能敏感的开发。", "有什么优势吗"),
            "Linux 原生性能更好，没有 WSL 的虚拟化开销，适合性能敏感的开发，大概是这样喵。",
        )
        self.assertEqual(_humanize_group_reply("不是，Windows 主力。", "主力机是linux吗"), "不是，Windows 主力喵")
        self.assertEqual(_humanize_group_reply("在", "宝宝"), "宝宝")
        self.assertEqual(_humanize_group_reply("在", "在吗"), "在喵")

    def test_should_use_reaction_instead_for_low_value_message(self):
        self.assertTrue(_should_use_reaction_instead("哈哈", "收到"))
        self.assertTrue(_should_use_reaction_instead("正常消息", "[[NO_REPLY]]"))
        self.assertFalse(_should_use_reaction_instead("你们怎么看这个方案？", "收到"))

    def test_explicit_trigger_no_reply_fallback_keeps_mentions_from_going_silent(self):
        fallback = _build_explicit_trigger_no_reply_fallback(
            "宝宝",
            [PendingGroupMessage(user_id=1, sender_name="u", text="宝宝", timestamp=1, explicit_trigger=True)],
            ResponseAction(kind=ActionKind.NO_REPLY, reason="explicit_no_reply_token"),
        )

        self.assertEqual(fallback, "在呢喵")

    def test_explicit_trigger_no_reply_fallback_respects_stop_request(self):
        fallback = _build_explicit_trigger_no_reply_fallback(
            "你别多嘴",
            [PendingGroupMessage(user_id=1, sender_name="u", text="你别多嘴", timestamp=1, explicit_trigger=True)],
            ResponseAction(kind=ActionKind.NO_REPLY, reason="explicit_no_reply_token"),
        )

        self.assertIsNone(fallback)

    def test_pick_reaction_target_message_id(self):
        batch = [
            PendingGroupMessage(user_id=1, sender_name="a", text="x", timestamp=1, message_id=None),
            PendingGroupMessage(user_id=2, sender_name="b", text="y", timestamp=2, message_id=98765),
        ]
        self.assertEqual(_pick_reaction_target_message_id(batch), 98765)

    def test_pick_text_reply_target_defaults_to_last_same_turn_message(self):
        batch = [
            PendingGroupMessage(user_id=1, sender_name="a", text="还活着没有", timestamp=1, message_id=111),
            PendingGroupMessage(user_id=1, sender_name="a", text="活着的话什么时候死一下", timestamp=2, message_id=222),
        ]

        self.assertEqual(_pick_text_reply_target_message_id(batch, "还在，别急"), 222)

    def test_pick_text_reply_target_prefers_question_over_later_chatter(self):
        batch = [
            PendingGroupMessage(user_id=1, sender_name="a", text="这个是什么？", timestamp=1, message_id=111),
            PendingGroupMessage(user_id=2, sender_name="b", text="笑死", timestamp=2, message_id=222),
        ]

        self.assertEqual(_pick_text_reply_target_message_id(batch, "看着像表情包"), 111)

    @patch("apps.qq_ai_bridge.services.group_chat_service.time.monotonic", return_value=105.0)
    def test_compute_turn_extension_for_same_user_followup(self, _mock_time):
        batch = [
            PendingGroupMessage(user_id=1, sender_name="a", text="还活着没有", timestamp=1, message_id=111),
            PendingGroupMessage(user_id=1, sender_name="a", text="活着的话什么时候死一下", timestamp=2, message_id=222),
        ]

        self.assertEqual(_compute_turn_extension_ms(batch, 100.0), 2000)

    @patch("apps.qq_ai_bridge.services.group_chat_service.time.monotonic", return_value=109.0)
    def test_compute_turn_extension_respects_max_window(self, _mock_time):
        batch = [
            PendingGroupMessage(user_id=1, sender_name="a", text="还活着没有", timestamp=1, message_id=111),
            PendingGroupMessage(user_id=1, sender_name="a", text="活着的话什么时候死一下", timestamp=2, message_id=222),
        ]

        self.assertEqual(_compute_turn_extension_ms(batch, 100.0), 0)

    def test_detect_direct_reaction_request_count(self):
        self.assertEqual(_detect_direct_reaction_request_count("给我贴个表情"), 0)
        self.assertEqual(_detect_direct_reaction_request_count("贴3个表情"), 0)
        self.assertEqual(_detect_direct_reaction_request_count("再贴一个不一样的"), 0)
        self.assertEqual(_detect_direct_reaction_request_count("给这条消息贴个表情"), 1)
        self.assertEqual(_detect_direct_reaction_request_count("消息上面贴几个常用表情"), 2)
        self.assertEqual(_detect_direct_reaction_request_count("再来几个，能给这条消息贴按按钮吗"), 2)

    def test_get_reaction_decision_mode_defaults_to_llm_first(self):
        self.assertEqual(_get_reaction_decision_mode({}), "llm_first")
        self.assertEqual(_get_reaction_decision_mode({"reaction_decision_mode": "rule_first"}), "rule_first")

    def test_parse_group_response_mode(self):
        self.assertEqual(_parse_group_response_mode('{"mode":"reaction","reason":"低价值"}')["mode"], "reaction")
        self.assertEqual(_parse_group_response_mode("mode=silence")["mode"], "silence")
        self.assertEqual(_parse_group_response_mode("unknown")["mode"], "silence")

    def test_extract_emoji_tag(self):
        self.assertEqual(_extract_emoji_tag("[emoji:doge]"), "doge")
        self.assertIsNone(_extract_emoji_tag("普通文本"))

    def test_is_global_listen_group(self):
        self.assertTrue(_is_global_listen_group(123, {"reply_all_messages": True}))
        self.assertFalse(_is_global_listen_group(123, {"reply_all_messages": False}))

    def test_should_silence_trivial_global_message(self):
        self.assertTrue(_should_silence_trivial_global_message("笑了", mentions_bot=False))
        self.assertTrue(_should_silence_trivial_global_message("666", mentions_bot=False))
        self.assertFalse(_should_silence_trivial_global_message("笑了，怎么回事？", mentions_bot=False))
        self.assertFalse(_should_silence_trivial_global_message("笑了", mentions_bot=True))

    def test_detect_repeat_follow_text_after_three_same_messages(self):
        batch = [
            PendingGroupMessage(user_id=1, sender_name="a", text="复读", timestamp=1),
            PendingGroupMessage(user_id=2, sender_name="b", text="别的", timestamp=2),
            PendingGroupMessage(user_id=3, sender_name="c", text="复读", timestamp=3),
            PendingGroupMessage(user_id=4, sender_name="d", text="复读", timestamp=4),
        ]

        self.assertEqual(_detect_repeat_follow_text(batch), ("复读", 3))

    def test_detect_repeat_follow_text_blocks_control_tags(self):
        batch = [
            PendingGroupMessage(user_id=1, sender_name="a", text="[CQ:face,id=66]", timestamp=1),
            PendingGroupMessage(user_id=2, sender_name="b", text="[CQ:face,id=66]", timestamp=2),
            PendingGroupMessage(user_id=3, sender_name="c", text="[CQ:face,id=66]", timestamp=3),
        ]

        self.assertEqual(_detect_repeat_follow_text(batch), ("", 0))

    def test_claim_repeat_follow_uses_cooldown(self):
        self.assertTrue(_claim_repeat_follow(123, "复读", now=100.0))
        self.assertFalse(_claim_repeat_follow(123, "复读", now=120.0))
        self.assertTrue(_claim_repeat_follow(123, "复读", now=161.0))

    @patch("apps.qq_ai_bridge.services.group_chat_service.call_ai")
    def test_group_response_mode_local_silences_trivial_before_llm(self, mock_call_ai):
        decision = _decide_group_response_mode_with_llm(
            merged_text="笑了",
            batch=[PendingGroupMessage(user_id=1, sender_name="u", text="笑了", timestamp=1, explicit_trigger=False)],
            group_config={"reply_all_messages": True},
            log=lambda *_args: None,
        )

        self.assertEqual(decision["mode"], "silence")
        mock_call_ai.assert_not_called()

    @patch("apps.qq_ai_bridge.services.group_chat_service.call_ai")
    def test_group_response_mode_local_reacts_to_goodnight_hint(self, mock_call_ai):
        decision = _decide_group_response_mode_with_llm(
            merged_text="睡觉了",
            batch=[PendingGroupMessage(user_id=1, sender_name="u", text="睡觉了", timestamp=1, explicit_trigger=False)],
            group_config={"reply_all_messages": True},
            log=lambda *_args: None,
        )

        self.assertEqual(decision["mode"], "reaction")
        self.assertEqual(decision["reason"], "goodnight_reaction_hint")
        mock_call_ai.assert_not_called()

    @patch("apps.qq_ai_bridge.services.group_chat_service.call_ai")
    def test_group_response_mode_local_reacts_to_sexual_hint(self, mock_call_ai):
        decision = _decide_group_response_mode_with_llm(
            merged_text="想摸地黄的大果睡",
            batch=[PendingGroupMessage(user_id=1, sender_name="u", text="想摸地黄的大果睡", timestamp=1, explicit_trigger=False)],
            group_config={"reply_all_messages": True},
            log=lambda *_args: None,
        )

        self.assertEqual(decision["mode"], "reaction")
        self.assertEqual(decision["reason"], "sexual_reaction_hint")
        mock_call_ai.assert_not_called()

    @patch("apps.qq_ai_bridge.services.group_chat_service.call_ai", return_value='{"mode":"silence","reason":"短消息"}')
    def test_group_response_mode_never_silences_explicit_trigger(self, _mock_call_ai):
        decision = _decide_group_response_mode_with_llm(
            merged_text="宝宝",
            batch=[PendingGroupMessage(user_id=1, sender_name="u", text="宝宝", timestamp=1, explicit_trigger=True)],
            group_config={"reply_all_messages": True},
            log=lambda *_args: None,
        )

        self.assertEqual(decision["mode"], "text")
        self.assertEqual(decision["reason"], "explicit_trigger_override")

    @patch("apps.qq_ai_bridge.services.group_chat_service.call_ai", return_value='{"mode":"silence","reason":"制止"}')
    def test_group_response_mode_respects_stop_talking_request(self, _mock_call_ai):
        decision = _decide_group_response_mode_with_llm(
            merged_text="你别多嘴",
            batch=[PendingGroupMessage(user_id=1, sender_name="u", text="你别多嘴", timestamp=1, explicit_trigger=True)],
            group_config={"reply_all_messages": True},
            log=lambda *_args: None,
        )

        self.assertEqual(decision["mode"], "silence")
        self.assertEqual(decision["reason"], "制止")

    def test_mention_only_group_never_absorbs_non_triggered_message(self):
        group_id = 810938203
        state = _get_group_chat_state(group_id)
        state.worker_running = True
        state.pending = [
            PendingGroupMessage(user_id=1, sender_name="u", text="已触发消息", timestamp=1, explicit_trigger=True)
        ]

        result = enqueue_group_text(
            group_id=group_id,
            user_id=2,
            sender_name="v",
            ai_query="普通跟聊",
            group_config={"reply_all_messages": False},
            explicit_trigger=False,
            timestamp=2,
            message_id=222,
            log=lambda *_args, **_kwargs: None,
        )
        self.assertFalse(result["queued"])
        self.assertEqual(result["reason"], "group_not_triggered")

    def test_enqueue_group_text_accepts_reply_reference(self):
        group_id = 123456
        state = _get_group_chat_state(group_id)
        state.worker_running = True
        result = enqueue_group_text(
            group_id=group_id,
            user_id=2,
            sender_name="v",
            ai_query="测试一下",
            group_config={"reply_all_messages": True},
            explicit_trigger=True,
            timestamp=2,
            message_id=222,
            reply_reference={"message_id": 111},
            log=lambda *_args, **_kwargs: None,
        )

        self.assertTrue(result["queued"])
        self.assertEqual(state.pending[-1].reply_reference, {"message_id": 111})
        state.pending.clear()
        state.worker_running = False

    @patch("apps.qq_ai_bridge.services.group_chat_service.infer_reaction_preferred_order", return_value=("laugh_cry",))
    @patch("apps.qq_ai_bridge.services.response_action.react_message_with_multiple_emojis")
    def test_group_worker_simulates_direct_reaction_request(self, mock_react, _mock_order):
        old_debounce = group_chat_service.GROUP_DEBOUNCE_MS
        group_chat_service.GROUP_DEBOUNCE_MS = 0
        _GROUP_CHAT_STATES.clear()
        mock_react.return_value = {"ok": True, "applied_count": 2, "emoji_names": ["laugh_cry", "red_button"]}
        logs = []

        try:
            result = enqueue_group_text(
                group_id=123456,
                user_id=2,
                sender_name="v",
                ai_query="给这条消息贴几个常用表情",
                group_config={"reply_all_messages": True},
                explicit_trigger=True,
                timestamp=2,
                message_id=222,
                log=logs.append,
            )
            deadline = time.time() + 2
            while time.time() < deadline and _get_group_chat_state(123456).worker_running:
                time.sleep(0.01)
        finally:
            group_chat_service.GROUP_DEBOUNCE_MS = old_debounce

        self.assertTrue(result["queued"])
        mock_react.assert_called_once()
        self.assertTrue(any("direct_reacted" in item for item in logs))

    @patch("apps.qq_ai_bridge.services.group_chat_service.call_ai")
    @patch("apps.qq_ai_bridge.services.group_chat_service.execute_group_action")
    def test_group_worker_follows_three_repeated_messages_before_llm(self, mock_execute, mock_call_ai):
        old_debounce = group_chat_service.GROUP_DEBOUNCE_MS
        group_chat_service.GROUP_DEBOUNCE_MS = 20
        mock_execute.return_value = {"ok": True}
        logs = []

        try:
            for user_id in (1, 2, 3):
                result = enqueue_group_text(
                    group_id=654321,
                    user_id=user_id,
                    sender_name=f"u{user_id}",
                    ai_query="复读一下",
                    group_config={"reply_all_messages": True},
                    explicit_trigger=False,
                    timestamp=user_id,
                    message_id=100 + user_id,
                    log=logs.append,
                )
                self.assertTrue(result["queued"])
            deadline = time.time() + 2
            while time.time() < deadline and _get_group_chat_state(654321).worker_running:
                time.sleep(0.01)
        finally:
            group_chat_service.GROUP_DEBOUNCE_MS = old_debounce

        mock_call_ai.assert_not_called()
        mock_execute.assert_called_once()
        action = mock_execute.call_args.args[1]
        self.assertEqual(action.kind, ActionKind.TEXT)
        self.assertEqual(action.text, "复读一下")
        self.assertTrue(any("repeat_followed" in item for item in logs))

    @patch("apps.qq_ai_bridge.services.group_chat_service.call_ai")
    @patch("apps.qq_ai_bridge.services.group_chat_service.execute_group_action")
    @patch("apps.qq_ai_bridge.services.group_chat_service._compute_turn_extension_ms", return_value=0)
    def test_group_worker_replies_to_selected_message_id(self, _mock_extension, mock_execute, mock_call_ai):
        old_debounce = group_chat_service.GROUP_DEBOUNCE_MS
        group_chat_service.GROUP_DEBOUNCE_MS = 20
        mock_call_ai.side_effect = ['{"mode":"text","reason":"明确提问"}', "还在，别急着办席"]
        mock_execute.return_value = {"ok": True}

        try:
            for text, message_id in (("还活着没有", 111), ("活着的话什么时候死一下", 222)):
                result = enqueue_group_text(
                    group_id=765432,
                    user_id=1,
                    sender_name="a",
                    ai_query=text,
                    group_config={"reply_all_messages": True},
                    explicit_trigger=False,
                    timestamp=message_id,
                    message_id=message_id,
                    log=lambda *_args: None,
                )
                self.assertTrue(result["queued"])
            deadline = time.time() + 2
            while time.time() < deadline and _get_group_chat_state(765432).worker_running:
                time.sleep(0.01)
        finally:
            group_chat_service.GROUP_DEBOUNCE_MS = old_debounce

        text_call = mock_execute.call_args
        self.assertEqual(text_call.kwargs.get("reply_to_message_id"), 222)


if __name__ == "__main__":
    unittest.main()
