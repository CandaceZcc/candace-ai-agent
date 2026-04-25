import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

try:
    from apps.qq_ai_bridge.adapters import webhook
except ModuleNotFoundError as exc:  # pragma: no cover - depends on optional Flask test env
    if exc.name != "flask":
        raise
    webhook = None


class WebhookImageCaptionTests(unittest.TestCase):
    def setUp(self):
        if webhook is None:
            self.skipTest("flask is not installed")
        webhook._PENDING_IMAGE_CAPTIONS.clear()

    def tearDown(self):
        webhook._PENDING_IMAGE_CAPTIONS.clear()

    def test_group_image_caption_window_is_five_seconds(self):
        self.assertEqual(webhook.IMAGE_CAPTION_GRACE_SECONDS, 5.0)

    @patch("apps.qq_ai_bridge.adapters.webhook.threading.Timer")
    @patch("apps.qq_ai_bridge.adapters.webhook.SkillDispatcher.dispatch")
    def test_same_user_followup_text_merges_with_pending_image(self, mock_dispatch, mock_timer):
        mock_timer.return_value.daemon = False
        image_event = {
            "type": "text",
            "msg_type": "group",
            "group_id": 1,
            "user_id": 2,
            "text": "",
            "raw_message": "[CQ:image]",
            "image_inputs": {"has_image": True, "image_urls": ["https://example.com/a.jpg"], "text": ""},
        }
        text_event = {
            "type": "text",
            "msg_type": "group",
            "group_id": 1,
            "user_id": 2,
            "text": "爸爸",
            "raw_message": "爸爸",
            "image_inputs": {"has_image": False, "image_urls": [], "text": "爸爸"},
        }

        image_handled = webhook._maybe_handle_image_caption_merge(image_event)
        text_handled = webhook._maybe_handle_image_caption_merge(text_event)

        self.assertTrue(image_handled)
        self.assertTrue(text_handled)
        merged = mock_dispatch.call_args.args[0]
        self.assertEqual(merged["text"], "爸爸")
        self.assertTrue(merged["image_inputs"]["has_image"])
        self.assertEqual(merged["image_inputs"]["text"], "爸爸")


if __name__ == "__main__":
    unittest.main()
