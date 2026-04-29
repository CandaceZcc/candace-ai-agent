import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.vision_service import VISION_USER_DOWNLOAD_FALLBACK, run_vision_pipeline


class VisionServiceTests(unittest.TestCase):
    @patch("apps.qq_ai_bridge.services.vision_service.download_image", side_effect=RuntimeError("broken download"))
    def test_download_failure_retries_without_traceback_log(self, mock_download):
        logs: list[str] = []

        result = run_vision_pipeline(["https://example.com/a.jpg"], "", logs.append, save_dir="/tmp")

        self.assertEqual(result, VISION_USER_DOWNLOAD_FALLBACK)
        self.assertEqual(mock_download.call_count, 2)
        self.assertTrue(any("[VISION][image_download_retry]" in item for item in logs))
        self.assertTrue(any("[VISION][image_url_unreachable]" in item for item in logs))
        self.assertFalse(any("[traceback]" in item for item in logs))


if __name__ == "__main__":
    unittest.main()
