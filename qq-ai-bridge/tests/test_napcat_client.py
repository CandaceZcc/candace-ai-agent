import sys
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.adapters.napcat_client import (
    react_message_with_preferred_emojis,
    send_group_msg,
    send_private_msg,
    split_outbound_messages,
)


class NapcatClientTests(unittest.TestCase):
    def test_split_outbound_messages_by_blank_line(self):
        parts = split_outbound_messages("第一段\n\n第二段")
        self.assertEqual(parts, ["第一段", "第二段"])

    def test_split_outbound_messages_filters_empty_segments(self):
        parts = split_outbound_messages("\n\n  \n\n第一段\n\n")
        self.assertEqual(parts, ["第一段"])

    def test_split_outbound_messages_by_send_split_token(self):
        parts = split_outbound_messages("第一条[[SEND_SPLIT]]第二条")
        self.assertEqual(parts, ["第一条", "第二条"])

    def test_split_outbound_messages_force_parts_when_single_segment(self):
        parts = split_outbound_messages("发不了 能发一条不错了", force_parts=2)
        self.assertEqual(len(parts), 2)

    @patch("apps.qq_ai_bridge.adapters.napcat_client.time.sleep", return_value=None)
    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_send_group_msg_sends_each_segment(self, mock_post, _mock_sleep):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text="ok")

        result = send_group_msg(12345, "段落A\n\n段落B", quiet=True)

        self.assertEqual(mock_post.call_count, 2)
        first_payload = mock_post.call_args_list[0].args[1]
        second_payload = mock_post.call_args_list[1].args[1]
        self.assertEqual(first_payload["message"], "段落A")
        self.assertEqual(second_payload["message"], "段落B")
        self.assertTrue(result["ok"])
        self.assertEqual(result["parts_sent"], 2)
        self.assertEqual(result["parts_total"], 2)

    @patch("apps.qq_ai_bridge.adapters.napcat_client.time.sleep", return_value=None)
    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_send_private_msg_keeps_single_send_without_split(self, mock_post, _mock_sleep):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text="ok")

        result = send_private_msg(67890, "单条消息", quiet=True)

        self.assertEqual(mock_post.call_count, 1)
        payload = mock_post.call_args_list[0].args[1]
        self.assertEqual(payload["message"], "单条消息")
        self.assertTrue(result["ok"])
        self.assertEqual(result["parts_sent"], 1)
        self.assertEqual(result["parts_total"], 1)

    @patch("apps.qq_ai_bridge.adapters.napcat_client.time.sleep", return_value=None)
    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_send_group_msg_force_parts_sends_multiple_messages(self, mock_post, _mock_sleep):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text="ok")

        result = send_group_msg(12345, "发不了 能发一条不错了", quiet=True, force_parts=2)

        self.assertEqual(mock_post.call_count, 2)
        self.assertTrue(result["ok"])
        self.assertEqual(result["parts_sent"], 2)
        self.assertEqual(result["parts_total"], 2)

    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_send_group_msg_can_reply_to_specific_message(self, mock_post):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text="ok")

        result = send_group_msg(12345, "收到", quiet=True, reply_to_message_id=998877)

        self.assertTrue(result["ok"])
        payload = mock_post.call_args.args[1]
        self.assertEqual(payload["group_id"], 12345)
        self.assertEqual(
            payload["message"],
            [
                {"type": "reply", "data": {"id": "998877"}},
                {"type": "text", "data": {"text": "收到"}},
            ],
        )

    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_react_message_with_preferred_emojis_fallback(self, mock_post):
        # First emoji candidate fails with retcode, second succeeds.
        mock_post.side_effect = [
            SimpleNamespace(ok=True, status_code=200, text='{"retcode":1}'),
            SimpleNamespace(ok=True, status_code=200, text='{"retcode":0}'),
        ]
        result = react_message_with_preferred_emojis(123456, quiet=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["emoji_name"], "laugh_cry")
        self.assertEqual(mock_post.call_count, 2)

    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_react_message_with_preferred_emojis_rotates_by_message_id(self, mock_post):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text='{"retcode":0}')
        result = react_message_with_preferred_emojis(1, quiet=True)
        self.assertTrue(result["ok"])
        self.assertEqual(result["emoji_name"], "red_button")
        self.assertEqual(mock_post.call_count, 1)


if __name__ == "__main__":
    unittest.main()
