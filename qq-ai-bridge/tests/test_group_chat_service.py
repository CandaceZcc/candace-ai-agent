import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.group_chat_service import (
    PendingGroupMessage,
    _GROUP_CHAT_STATES,
    _get_group_chat_state,
    _detect_direct_reaction_request_count,
    _detect_requested_parts,
    enqueue_group_text,
    _get_reaction_decision_mode,
    _humanize_group_reply,
    _pick_reaction_target_message_id,
    _should_use_reaction_instead,
)


class GroupChatServiceTests(unittest.TestCase):
    def setUp(self):
        _GROUP_CHAT_STATES.clear()

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

    def test_should_use_reaction_instead_for_low_value_message(self):
        self.assertTrue(_should_use_reaction_instead("哈哈", "收到"))
        self.assertTrue(_should_use_reaction_instead("正常消息", "[[NO_REPLY]]"))
        self.assertFalse(_should_use_reaction_instead("你们怎么看这个方案？", "收到"))

    def test_pick_reaction_target_message_id(self):
        batch = [
            PendingGroupMessage(user_id=1, sender_name="a", text="x", timestamp=1, message_id=None),
            PendingGroupMessage(user_id=2, sender_name="b", text="y", timestamp=2, message_id=98765),
        ]
        self.assertEqual(_pick_reaction_target_message_id(batch), 98765)

    def test_detect_direct_reaction_request_count(self):
        self.assertEqual(_detect_direct_reaction_request_count("给我贴个表情"), 1)
        self.assertEqual(_detect_direct_reaction_request_count("给我贴几个常用表情"), 2)
        self.assertEqual(_detect_direct_reaction_request_count("贴3个表情"), 3)

    def test_get_reaction_decision_mode_defaults_to_llm_first(self):
        self.assertEqual(_get_reaction_decision_mode({}), "llm_first")
        self.assertEqual(_get_reaction_decision_mode({"reaction_decision_mode": "rule_first"}), "rule_first")

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


if __name__ == "__main__":
    unittest.main()
