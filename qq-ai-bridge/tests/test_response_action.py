import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.response_action import ActionKind, ResponseAction, execute_group_action, parse_llm_response_action


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

    def test_execute_group_text_can_reply_to_message(self):
        from unittest.mock import patch

        with patch("apps.qq_ai_bridge.services.response_action.send_group_msg") as mock_send:
            result = execute_group_action(
                12345,
                ResponseAction(kind=ActionKind.TEXT, text="收到"),
                target_message_id=None,
                quiet=True,
                reply_to_message_id=998877,
            )

        self.assertTrue(result["ok"])
        mock_send.assert_called_once_with(12345, "收到", quiet=True, force_parts=None, reply_to_message_id=998877)


if __name__ == "__main__":
    unittest.main()
