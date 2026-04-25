import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.adapters.message_parser import extract_at_targets, extract_reply_reference


class MessageParserTests(unittest.TestCase):
    def test_extract_reply_reference_from_message_segment(self):
        payload = {
            "message": [
                {"type": "reply", "data": {"id": "9988"}},
                {"type": "text", "data": {"text": "接这个"}},
            ]
        }

        result = extract_reply_reference(payload)

        self.assertEqual(result, {"message_id": "9988"})

    def test_extract_at_targets_from_message_segments(self):
        payload = {
            "message": [
                {"type": "at", "data": {"qq": "12345"}},
                {"type": "text", "data": {"text": "在吗"}},
            ]
        }

        self.assertEqual(extract_at_targets(payload), ["12345"])

    def test_extract_reply_reference_keeps_sender_id(self):
        payload = {
            "message": [
                {"type": "reply", "data": {"id": "9988", "sender_id": "12345"}},
                {"type": "text", "data": {"text": "接这个"}},
            ]
        }

        self.assertEqual(extract_reply_reference(payload), {"message_id": "9988", "sender_id": "12345"})


if __name__ == "__main__":
    unittest.main()
