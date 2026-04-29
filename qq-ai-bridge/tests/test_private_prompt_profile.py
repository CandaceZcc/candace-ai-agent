import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.prompt_service import prepare_private_ai_prompt
from apps.qq_ai_bridge.services.user_profile_service import update_private_user_profile
from storage_utils import append_private_history


class PrivatePromptProfileTests(unittest.TestCase):
    def test_prepare_private_ai_prompt_includes_structured_profile_summary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            update_private_user_profile(tmpdir, 123, "我喜欢电影和摄影")
            append_private_history(tmpdir, 123, "你好", "你好呀", user_timestamp=1, assistant_timestamp=2)

            with patch("apps.qq_ai_bridge.services.prompt_service.BASE_DATA_DIR", tmpdir):
                payload = prepare_private_ai_prompt(123, "最近想买个相机", current_timestamp=3)

            self.assertIn("Structured user profile", payload["prompt"])
            self.assertIn("电影", payload["prompt"])
            self.assertIn("摄影", payload["prompt"])

    def test_private_prompt_mentions_builtin_admin_commands(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("apps.qq_ai_bridge.services.prompt_service.BASE_DATA_DIR", tmpdir):
                payload = prepare_private_ai_prompt(123, "查看群策略", current_timestamp=3)

        self.assertIn("owner-only bridge configuration", payload["prompt"])
        self.assertIn("查看某群的策略", payload["prompt"])


if __name__ == "__main__":
    unittest.main()
