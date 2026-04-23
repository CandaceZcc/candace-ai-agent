import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.prompt_service import (
    _build_group_history_lines,
    _build_group_quoted_context,
    prepare_group_ai_prompt,
)
from storage_utils import append_group_chat_log, save_json_file


class PromptServiceQuotedContextTests(unittest.TestCase):
    @patch("apps.qq_ai_bridge.adapters.napcat_client.get_msg_detail")
    def test_build_group_quoted_context(self, mock_get_msg_detail):
        mock_get_msg_detail.return_value = {
            "sender": {"nickname": "Alice"},
            "message": [{"type": "text", "data": {"text": "上一条原文"}}],
        }

        result = _build_group_quoted_context({"reply_references": [{"message_id": "123"}]})

        self.assertIn("Alice", result)
        self.assertIn("上一条原文", result)

    def test_build_group_history_lines_keeps_image_classification_hint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chat_log_path = Path(tmpdir) / "chat_log.json"
            save_json_file(
                str(chat_log_path),
                [
                    {
                        "sender_name": "tester",
                        "message": "[图片] 哈哈这图",
                        "source": "image_understanding:reaction",
                        "image_type": "meme",
                        "social_intent": "joke",
                    }
                ],
            )

            lines = _build_group_history_lines(str(chat_log_path), history_limit=4, history_char_budget=200)

            self.assertTrue(lines)
            self.assertIn("meme", lines[0])
            self.assertIn("joke", lines[0])

    def test_prepare_group_ai_prompt_includes_image_history_hint(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            group_dir = Path(tmpdir) / "groups" / "123"
            group_dir.mkdir(parents=True, exist_ok=True)
            save_json_file(
                str(group_dir / "chat_log.json"),
                [
                    {
                        "sender_name": "tester",
                        "message": "[图片] 哈哈这图",
                        "source": "image_understanding:reaction",
                        "image_type": "meme",
                        "social_intent": "joke",
                    }
                ],
            )
            save_json_file(str(group_dir / "style_profiles" / "group_style.json"), {})

            with patch("apps.qq_ai_bridge.services.prompt_service.BASE_DATA_DIR", tmpdir):
                payload = prepare_group_ai_prompt(123, "这图后劲挺大", user_id=1, group_config={})

            self.assertIn("meme/joke/reaction", payload["prompt"])
            self.assertIn("最近图片上下文", payload["prompt"])
            self.assertIn("上一张图", payload["prompt"])

    def test_simulated_image_then_text_flow_keeps_recent_image_context(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            group_id = 123
            append_group_chat_log(
                tmpdir,
                group_id,
                {
                    "timestamp": 1,
                    "sender_name": "tester",
                    "user_id": 1,
                    "message": "[图片] 哈哈这图",
                    "assistant": "有梗。",
                    "source": "image_understanding:reaction",
                    "image_type": "meme",
                    "social_intent": "joke",
                },
            )
            append_group_chat_log(
                tmpdir,
                group_id,
                {
                    "timestamp": 2,
                    "sender_name": "tester",
                    "user_id": 1,
                    "message": "这图后劲挺大",
                    "assistant": "确实有点典",
                    "source": "group_chat",
                },
            )

            with patch("apps.qq_ai_bridge.services.prompt_service.BASE_DATA_DIR", tmpdir):
                payload = prepare_group_ai_prompt(group_id, "越看越典", user_id=1, group_config={})

            self.assertIn("最近图片上下文", payload["prompt"])
            self.assertIn("上一张图：[图片] 哈哈这图 [meme/joke]", payload["prompt"])
            self.assertIn("tester: 这图后劲挺大", payload["prompt"])


if __name__ == "__main__":
    unittest.main()
