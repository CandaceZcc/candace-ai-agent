import os
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.adapters.napcat_client import (
    react_message_with_multiple_emojis,
    react_message_with_preferred_emojis,
    send_group_file,
    send_group_image,
    send_group_msg,
    send_private_image,
    send_private_msg,
    split_outbound_messages,
)


class NapcatClientTests(unittest.TestCase):
    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_send_private_image_uses_onebot_image_segment(self, mock_post):
        mock_post.return_value = SimpleNamespace(
            ok=True,
            status_code=200,
            text='{"retcode":0}',
        )

        result = send_private_image(67890, "https://cdn.example.com/result.png", quiet=True)

        self.assertTrue(result["ok"])
        self.assertEqual(mock_post.call_args.args[0], "send_private_msg")
        self.assertEqual(
            mock_post.call_args.args[1]["message"],
            [
                {
                    "type": "image",
                    "data": {"file": "https://cdn.example.com/result.png"},
                }
            ],
        )

    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_send_group_image_can_reply_to_trigger_message(self, mock_post):
        mock_post.return_value = SimpleNamespace(
            ok=True,
            status_code=200,
            text='{"retcode":0}',
        )

        result = send_group_image(
            12345,
            "https://cdn.example.com/result.png",
            quiet=True,
            reply_to_message_id=998877,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(mock_post.call_args.args[0], "send_group_msg")
        self.assertEqual(
            mock_post.call_args.args[1]["message"],
            [
                {"type": "reply", "data": {"id": "998877"}},
                {
                    "type": "image",
                    "data": {"file": "https://cdn.example.com/result.png"},
                },
            ],
        )

    def test_split_outbound_messages_by_blank_line(self):
        parts = split_outbound_messages("第一段\n\n第二段")
        self.assertEqual(parts, ["第一段", "第二段"])

    def test_split_outbound_messages_filters_empty_segments(self):
        parts = split_outbound_messages("\n\n  \n\n第一段\n\n")
        self.assertEqual(parts, ["第一段"])

    def test_send_group_msg_reports_empty_sanitized_message(self):
        result = send_group_msg(12345, "？", quiet=True)

        self.assertFalse(result["ok"])
        self.assertEqual(result["reason"], "empty_message")

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

    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_send_group_file_uploads_local_file(self, mock_post):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text='{ "retcode": 0 }')
        with tempfile.NamedTemporaryFile("w", delete=False, encoding="utf-8") as file_obj:
            file_obj.write("print('hi')\n")
            file_path = file_obj.name
        try:
            result = send_group_file(12345, file_path, name="demo.py", quiet=True)
        finally:
            os.unlink(file_path)

        self.assertTrue(result["ok"])
        self.assertEqual(mock_post.call_args.args[0], "upload_group_file")
        payload = mock_post.call_args.args[1]
        self.assertEqual(payload["group_id"], 12345)
        self.assertEqual(payload["file"], file_path)
        self.assertEqual(payload["name"], "demo.py")

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

    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_send_private_msg_converts_cq_face_to_message_segment(self, mock_post):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text="ok")

        result = send_private_msg(67890, "[CQ:face,id=66]", quiet=True, reply_to_message_id=123456)

        self.assertTrue(result["ok"])
        payload = mock_post.call_args.args[1]
        self.assertEqual(
            payload["message"],
            [
                {"type": "reply", "data": {"id": "123456"}},
                {"type": "face", "data": {"id": "66"}},
            ],
        )

    @patch("builtins.print")
    @patch("apps.qq_ai_bridge.adapters.napcat_client._append_outbound_event")
    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_sensitive_private_message_redacts_console_and_audit(
        self,
        mock_post,
        mock_event,
        mock_print,
    ):
        secret_text = "Private exam summary from Teacher"
        mock_post.return_value = SimpleNamespace(
            ok=True,
            status_code=200,
            text='{"status":"ok","retcode":0}',
        )

        result = send_private_msg(
            67890,
            secret_text,
            quiet=False,
            redact_content=True,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(mock_post.call_args.args[1]["message"], secret_text)
        console_text = " ".join(str(call) for call in mock_print.call_args_list)
        event = mock_event.call_args.args[0]
        self.assertNotIn(secret_text, console_text)
        self.assertNotIn(secret_text, repr(event))
        self.assertEqual(event["message_preview"], "[redacted]")
        self.assertEqual(event["message_chars"], len(secret_text))
        self.assertEqual(event["response_preview"], "[redacted]")

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

    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_react_message_with_preferred_emojis_supports_new_candidates(self, mock_post):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text='{"retcode":0}')
        result = react_message_with_preferred_emojis(123, quiet=True, preferred_order=("explode_marker",))
        self.assertTrue(result["ok"])
        self.assertEqual(result["emoji_name"], "explode_marker")

    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_react_message_with_preferred_emojis_supports_official_candidates(self, mock_post):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text='{"retcode":0}')

        result = react_message_with_preferred_emojis(123, quiet=True, preferred_order=("button_marker",))

        self.assertTrue(result["ok"])
        self.assertEqual(result["emoji_name"], "button_marker")
        self.assertEqual(mock_post.call_args.args[1]["emoji_id"], "424")

    @patch("apps.qq_ai_bridge.adapters.napcat_client.time.sleep", return_value=None)
    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_react_message_with_multiple_emojis_applies_distinct_reactions(self, mock_post, _mock_sleep):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text='{"retcode":0}')

        result = react_message_with_multiple_emojis(123456, count=3, quiet=True)

        self.assertTrue(result["ok"])
        self.assertEqual(result["applied_count"], 3)
        self.assertEqual(mock_post.call_count, 3)

    @patch("apps.qq_ai_bridge.adapters.napcat_client._append_outbound_event")
    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_react_message_with_multiple_emojis_can_preserve_preferred_order(self, mock_post, _mock_event):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text='{"retcode":0}')

        result = react_message_with_multiple_emojis(
            123456,
            count=2,
            quiet=True,
            preferred_order=("red_button", "laugh_cry", "lollipop"),
            preserve_order=True,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["emoji_names"], ["red_button", "laugh_cry"])
        self.assertEqual(mock_post.call_args_list[0].args[1]["emoji_id"], "66")

    @patch("apps.qq_ai_bridge.adapters.napcat_client._append_outbound_event")
    @patch("apps.qq_ai_bridge.adapters.napcat_client._post_json")
    def test_react_message_with_multiple_emojis_supports_official_ids(self, mock_post, _mock_event):
        mock_post.return_value = SimpleNamespace(ok=True, status_code=200, text='{"retcode":0}')

        result = react_message_with_multiple_emojis(
            123456,
            count=3,
            quiet=True,
            preferred_order=("watermelon", "awkward", "surprised"),
            preserve_order=True,
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["emoji_names"], ["watermelon", "awkward", "surprised"])
        self.assertEqual([call.args[1]["emoji_id"] for call in mock_post.call_args_list], ["89", "10", "0"])


if __name__ == "__main__":
    unittest.main()
