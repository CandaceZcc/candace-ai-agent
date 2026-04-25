import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.adapters.message_parser import format_forward_messages
from apps.qq_ai_bridge.services.group_chat_service import PendingGroupMessage, _decide_group_response_mode_with_llm

try:
    from apps.qq_ai_bridge.adapters import webhook
except ModuleNotFoundError as exc:  # pragma: no cover - optional Flask env
    if exc.name != "flask":
        raise
    webhook = None


class ForwardChatRecordTests(unittest.TestCase):
    def test_format_forward_messages_keeps_text_image_and_nested_record(self):
        payload = {
            "data": {
                "messages": [
                    {"sender": {"nickname": "A"}, "message": [{"type": "text", "data": {"text": "看这个"}}]},
                    {"sender": {"nickname": "B"}, "message": [{"type": "image", "data": {"summary": "[动画表情]"}}]},
                    {"name": "C", "content": [{"type": "forward", "data": {"id": "nested"}}]},
                ]
            }
        }

        text = format_forward_messages(payload)

        self.assertIn("A：看这个", text)
        self.assertIn("B：[动画表情]", text)
        self.assertIn("C：[聊天记录]", text)

    @patch("apps.qq_ai_bridge.services.group_chat_service.call_ai")
    def test_forwarded_chat_record_forces_text_mode_before_llm(self, mock_call_ai):
        decision = _decide_group_response_mode_with_llm(
            merged_text="[聊天记录]\nA：看这个\nB：[图片]",
            batch=[PendingGroupMessage(user_id=1, sender_name="u", text="[聊天记录]", timestamp=1, explicit_trigger=False)],
            group_config={"reply_all_messages": True},
            log=lambda *_args: None,
        )

        self.assertEqual(decision["mode"], "text")
        self.assertEqual(decision["reason"], "forwarded_chat_record")
        mock_call_ai.assert_not_called()

    def test_attach_forward_text_if_present_merges_resolved_forward(self):
        if webhook is None:
            self.skipTest("flask is not installed")
        raw_event = {"message": [{"type": "forward", "data": {"id": "abc"}}]}
        parsed = {"type": "text", "text": "", "raw_message": "", "image_inputs": {"has_image": False, "text": ""}}
        payload = {"data": {"messages": [{"name": "A", "message": [{"type": "text", "data": {"text": "笑死"}}]}]}}

        with patch("apps.qq_ai_bridge.adapters.webhook.get_forward_msg", return_value=payload):
            merged = webhook._attach_forward_text_if_present(raw_event, parsed)

        self.assertIn("[聊天记录]", merged["text"])
        self.assertIn("A：笑死", merged["text"])
        self.assertEqual(merged["image_inputs"]["text"], merged["text"])


if __name__ == "__main__":
    unittest.main()
