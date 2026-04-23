import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.image_social_service import classify_group_image_social, rewrite_group_vision_reply


class ImageSocialServiceTests(unittest.TestCase):
    @patch("apps.qq_ai_bridge.services.image_social_service.download_image", side_effect=RuntimeError("skip"))
    def test_image_only_prefers_reaction(self, _mock_download):
        result = classify_group_image_social(["https://example.com/a.jpg"], "")
        self.assertEqual(result.suggested_action, "reaction")

    @patch("apps.qq_ai_bridge.services.image_social_service.download_image", side_effect=RuntimeError("skip"))
    def test_identify_request_prefers_full_text(self, _mock_download):
        result = classify_group_image_social(["https://example.com/a.jpg"], "这图写了啥")
        self.assertEqual(result.suggested_action, "full_text")
        self.assertEqual(result.social_intent, "ask_identify")

    @patch("apps.qq_ai_bridge.services.image_social_service.download_image", side_effect=RuntimeError("skip"))
    def test_showoff_text_prefers_human_short_reply(self, _mock_download):
        result = classify_group_image_social(["https://example.com/a.jpg"], "哈哈这图")
        self.assertEqual(result.suggested_action, "short_text")
        self.assertTrue(result.short_text)

    def test_rewrite_group_reply_removes_manual_description_prefix(self):
        class Dummy:
            image_type = "meme"
            social_intent = "joke"
            suggested_action = "short_text"

        rewritten = rewrite_group_vision_reply("这是一张猫猫表情包，挺搞笑的", Dummy(), "")
        self.assertNotIn("这是一张", rewritten)


if __name__ == "__main__":
    unittest.main()
