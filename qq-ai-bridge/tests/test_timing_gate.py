import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.group_chat_service import PendingGroupMessage
from apps.qq_ai_bridge.services.reply_models import ReplyMode
from apps.qq_ai_bridge.services.timing_gate import evaluate_group_timing_gate


class TimingGateTests(unittest.TestCase):
    def test_timing_gate_prefers_silence_for_short_filler(self):
        decision = evaluate_group_timing_gate(
            123,
            [PendingGroupMessage(user_id=1, sender_name="a", text="哈哈", timestamp=1)],
            {},
        )

        self.assertIsNotNone(decision)
        self.assertFalse(decision.should_reply)
        self.assertEqual(decision.mode, ReplyMode.NO_REPLY)


if __name__ == "__main__":
    unittest.main()
