import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.adapters.message_parser import extract_reply_reference


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


if __name__ == "__main__":
    unittest.main()
