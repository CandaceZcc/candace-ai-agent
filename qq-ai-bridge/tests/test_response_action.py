import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.response_action import (
    ActionKind,
    ResponseAction,
    execute_group_action,
    execute_private_action,
    parse_llm_response_action,
)


class ResponseActionTests(unittest.TestCase):
    def test_parse_no_reply_token(self):
        action = parse_llm_response_action("[[NO_REPLY]]")
        self.assertEqual(action.kind, ActionKind.NO_REPLY)

    def test_parse_legacy_emoji_tag_blocked(self):
        action = parse_llm_response_action("[emoji:doge]")
        self.assertEqual(action.kind, ActionKind.NO_REPLY)

    def test_parse_json_reaction_action(self):
        action = parse_llm_response_action('{"action":"reaction","count":2,"preferred_order":["laugh_cry"]}')
        self.assertEqual(action.kind, ActionKind.REACTION)
        self.assertEqual(action.reaction_count, 2)
        self.assertEqual(action.preferred_order, ("laugh_cry",))

    def test_parse_plain_text(self):
        action = parse_llm_response_action("你好呀")
        self.assertEqual(action.kind, ActionKind.TEXT)
        self.assertEqual(action.text, "你好呀")

    def test_parse_markdown_list_collapses_to_plain_text(self):
        action = parse_llm_response_action("**两个选择：**\n\n1. 改仅艾特\n2. 调概率")

        self.assertEqual(action.kind, ActionKind.TEXT)
        self.assertNotIn("**", action.text)
        self.assertNotIn("\n\n", action.text)

    def test_private_markdown_table_becomes_readable_lines(self):
        action = parse_llm_response_action(
            "**账单**\n\n| 项目 | 金额 |\n|------|------|\n| Kimi | 50 |\n| 查重 | 102 |",
            surface="private",
        )

        self.assertEqual(action.kind, ActionKind.TEXT)
        self.assertIn("项目 金额", action.text)
        self.assertIn("Kimi 50", action.text)
        self.assertIn("\n", action.text)

    def test_private_plain_text_keeps_date_like_expense_names(self):
        action = parse_llm_response_action("4.26火锅 122\n4.24外食 80", surface="private")

        self.assertEqual(action.kind, ActionKind.TEXT)
        self.assertIn("4.26火锅", action.text)

    def test_unknown_json_is_not_user_visible_text(self):
        action = parse_llm_response_action('{"foo":"bar"}')

        self.assertEqual(action.kind, ActionKind.NO_REPLY)

    def test_execute_group_text_can_reply_to_message(self):
        from unittest.mock import patch

        with patch("apps.qq_ai_bridge.services.response_action.send_group_msg", return_value={"ok": True}) as mock_send:
            result = execute_group_action(
                12345,
                ResponseAction(kind=ActionKind.TEXT, text="收到"),
                target_message_id=None,
                quiet=True,
                reply_to_message_id=998877,
            )

        self.assertTrue(result["ok"])
        mock_send.assert_called_once_with(12345, "收到", quiet=True, force_parts=None, reply_to_message_id=998877)

    def test_execute_group_text_propagates_empty_send_failure(self):
        from unittest.mock import patch

        with patch("apps.qq_ai_bridge.services.response_action.send_group_msg", return_value={"ok": False, "reason": "empty_message"}):
            result = execute_group_action(
                12345,
                ResponseAction(kind=ActionKind.TEXT, text="？"),
                target_message_id=None,
                quiet=True,
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "empty_message")

    def test_execute_private_text_passes_force_parts(self):
        from unittest.mock import patch

        with patch("apps.qq_ai_bridge.services.response_action.send_private_msg", return_value={"ok": True}) as mock_send:
            result = execute_private_action(
                12345,
                ResponseAction(kind=ActionKind.TEXT, text="完整账单"),
                target_message_id=None,
                quiet=True,
                force_parts=3,
            )

        self.assertTrue(result["ok"])
        mock_send.assert_called_once_with(12345, "完整账单", quiet=True, force_parts=3)


if __name__ == "__main__":
    unittest.main()
