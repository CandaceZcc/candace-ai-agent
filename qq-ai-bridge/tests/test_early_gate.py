import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.early_gate import gate_parsed_event, gate_raw_event


class EarlyGateTests(unittest.TestCase):
    def test_drop_notice_event(self):
        result = gate_raw_event({"post_type": "notice"})
        self.assertTrue(result.dropped)
        self.assertEqual(result.reason, "notice_event")

    def test_drop_self_message(self):
        result = gate_raw_event({"post_type": "message", "self_id": 1, "user_id": 1})
        self.assertTrue(result.dropped)
        self.assertEqual(result.reason, "self_message")

    def test_drop_empty_parsed_message(self):
        result = gate_parsed_event(
            {
                "type": "text",
                "group_id": 1,
                "user_id": 2,
                "text": "",
                "image_inputs": {"has_image": False},
            }
        )
        self.assertTrue(result.dropped)
        self.assertEqual(result.reason, "empty_message")


if __name__ == "__main__":
    unittest.main()
