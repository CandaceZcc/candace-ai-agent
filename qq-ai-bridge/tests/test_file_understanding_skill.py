import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.config.settings import ALLOWED_PRIVATE_USER
from apps.qq_ai_bridge.skills.file_understanding import FileUnderstandingSkill


class FileUnderstandingSkillTests(unittest.TestCase):
    def _context(self, *, message_type="group", group_config=None, user_id=1):
        return SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type=message_type,
            user_id=user_id,
            self_id=2,
            group_id=1041622553 if message_type == "group" else None,
            group_config=group_config or {},
            should_log=True,
            msg="",
            normalized_msg="",
            effective_text="",
            mentioned_self=True,
            image_inputs={},
            file_info={"name": "demo.txt", "url": "https://example.com/demo.txt"},
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

    @patch("apps.qq_ai_bridge.skills.file_understanding.handle_file_message")
    def test_group_file_ignored_in_non_global_mode(self, mock_handle):
        result = FileUnderstandingSkill().handle(self._context(group_config={"reply_all_messages": False}))

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_handle.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.file_understanding.handle_file_message")
    def test_group_file_ignored_in_global_mode(self, mock_handle):
        result = FileUnderstandingSkill().handle(self._context(group_config={"reply_all_messages": True}))

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        self.assertIsNone(result.response_payload)
        mock_handle.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.file_understanding.handle_file_message")
    def test_private_file_still_handled_for_owner(self, mock_handle):
        mock_handle.return_value = {"status": "file_processed_private"}

        result = FileUnderstandingSkill().handle(
            self._context(message_type="private", user_id=ALLOWED_PRIVATE_USER)
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.response_payload, {"status": "file_processed_private"})
        mock_handle.assert_called_once()

    @patch("apps.qq_ai_bridge.skills.file_understanding.handle_file_message")
    def test_private_file_ignored_for_unauthorized_user(self, mock_handle):
        result = FileUnderstandingSkill().handle(self._context(message_type="private", user_id=999))

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_handle.assert_not_called()


if __name__ == "__main__":
    unittest.main()
