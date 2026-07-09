import sys
import time
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.quick_reply_policy import decide_quick_reply
from apps.qq_ai_bridge.services.reply_models import IncomingMessage, ReplyMode, TopicWindow


class QuickReplyPolicyTests(unittest.TestCase):
    def test_cute_short_message_prefers_local_text(self):
        topic = TopicWindow(
            group_id=123,
            messages=[IncomingMessage(user_id=1, sender_name="a", text="麦麦", timestamp=1)],
            started_at=time.monotonic(),
            last_event_at=time.monotonic(),
            replied=False,
            topic_key="maimai",
        )
        decision = decide_quick_reply(topic, {})
        self.assertIsNotNone(decision)
        self.assertEqual(decision.mode, ReplyMode.TEXT)
        self.assertTrue(decision.text)

    def test_filler_message_prefers_silence(self):
        topic = TopicWindow(
            group_id=123,
            messages=[IncomingMessage(user_id=1, sender_name="a", text="哈哈", timestamp=1)],
            started_at=time.monotonic(),
            last_event_at=time.monotonic(),
            replied=False,
            topic_key="haha",
        )
        decision = decide_quick_reply(topic, {})
        self.assertIsNotNone(decision)
        self.assertFalse(decision.should_reply)
        self.assertEqual(decision.mode, ReplyMode.NO_REPLY)
        self.assertEqual(decision.reason, "short_filler_silence")

    def test_replied_topic_stays_quiet(self):
        topic = TopicWindow(
            group_id=123,
            messages=[IncomingMessage(user_id=1, sender_name="a", text="在喵", timestamp=1)],
            started_at=time.monotonic(),
            last_event_at=time.monotonic(),
            replied=True,
            topic_key="miaomiao",
        )
        decision = decide_quick_reply(topic, {})
        self.assertIsNotNone(decision)
        self.assertEqual(decision.mode, ReplyMode.NO_REPLY)


if __name__ == "__main__":
    unittest.main()
