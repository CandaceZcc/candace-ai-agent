import sys
import tempfile
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.user_profile_service import (
    load_private_user_profile_summary,
    update_private_user_profile,
)
from storage_utils import load_json_file


class UserProfileServiceTests(unittest.TestCase):
    def test_update_private_user_profile_extracts_preferences_and_identity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            update_private_user_profile(tmpdir, 123, "我喜欢摇滚，也喜欢 Radiohead")
            update_private_user_profile(tmpdir, 123, "我讨厌太吵的酒吧")
            update_private_user_profile(tmpdir, 123, "我是产品经理")

            profile = load_json_file(
                f"{tmpdir}/private_users/123/profile.json",
                {},
            )

            self.assertIn("摇滚", profile.get("likes", []))
            self.assertIn("Radiohead", profile.get("likes", []))
            self.assertIn("太吵的酒吧", profile.get("dislikes", []))
            self.assertIn("产品经理", profile.get("identity_tags", []))

    def test_load_private_user_profile_summary_returns_compact_readable_text(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            update_private_user_profile(tmpdir, 123, "我喜欢摄影和旅行")
            update_private_user_profile(tmpdir, 123, "最近一直在聊相机")

            summary = load_private_user_profile_summary(tmpdir, 123)

            self.assertIn("偏好", summary)
            self.assertIn("摄影", summary)
            self.assertIn("旅行", summary)
            self.assertIn("最近在聊", summary)


if __name__ == "__main__":
    unittest.main()
