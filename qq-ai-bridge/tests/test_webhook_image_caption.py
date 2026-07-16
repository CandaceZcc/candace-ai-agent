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

    def test_group_file_notice_always_disabled(self):
        self.assertFalse(webhook._should_handle_group_file_notice(123, {"reply_all_messages": False}))
        self.assertFalse(webhook._should_handle_group_file_notice(123, {"reply_all_messages": True}))

    def test_pending_image_caption_map_evicts_oldest_entry_at_capacity(self):
        for index in range(3):
            webhook._store_pending_image_caption(
                f"group:1:{index}",
                {"group_id": 1, "user_id": index},
                now=float(index + 1),
                max_entries=2,
            )

        self.assertEqual(set(webhook._PENDING_IMAGE_CAPTIONS), {"group:1:1", "group:1:2"})

    @patch("apps.qq_ai_bridge.adapters.webhook.schedule_task", return_value=True)
    @patch("apps.qq_ai_bridge.adapters.webhook.SkillDispatcher.dispatch")
    def test_same_user_followup_text_merges_with_pending_image(self, mock_dispatch, mock_schedule):
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
        mock_schedule.assert_called_once()
        self.assertIs(mock_schedule.call_args.args[1], webhook._submit_pending_image_caption_flush)

    @patch("apps.qq_ai_bridge.adapters.webhook.submit_media_task", return_value=object())
    @patch("apps.qq_ai_bridge.adapters.webhook._flush_pending_image_caption")
    def test_caption_timeout_submits_dispatch_to_media_pool(self, mock_flush, mock_submit):
        webhook._submit_pending_image_caption_flush("group:1:2")

        mock_submit.assert_called_once_with(mock_flush, "group:1:2")

    @patch("apps.qq_ai_bridge.adapters.webhook._send_group_msg_raw")
    @patch("apps.qq_ai_bridge.adapters.webhook.submit_media_task", return_value=None)
    def test_caption_timeout_media_rejection_notifies_group(self, _mock_submit, mock_send):
        key = "group:1:2"
        webhook._store_pending_image_caption(
            key,
            {"group_id": 1, "user_id": 2, "message_id": 3},
        )

        webhook._submit_pending_image_caption_flush(key)

        self.assertNotIn(key, webhook._PENDING_IMAGE_CAPTIONS)
        mock_send.assert_called_once_with(
            1,
            "当前图片处理任务较多，请稍后再试。",
            quiet=True,
            reply_to_message_id=3,
        )


if __name__ == "__main__":
    unittest.main()
