import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.prompt_service import (
    _build_group_history_lines,
    _build_recent_image_context,
    _build_group_quoted_context,
    prepare_group_ai_prompt,
)
from storage_utils import append_group_chat_log, save_json_file


class PromptServiceQuotedContextTests(unittest.TestCase):
    def test_group_history_includes_assistant_from_legacy_combined_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chat_log_path = Path(tmpdir) / "chat_log.json"
            save_json_file(
                str(chat_log_path),
                [
                    {
                        "timestamp": 1,
                        "sender_name": "群友A",
                        "message": "深圳吗",
                        "assistant": "深圳？你咋突然问这个",
                    },
                    {"timestamp": 2, "sender_name": "群友A", "message": "何意味"},
                ],
            )

            lines = _build_group_history_lines(str(chat_log_path), history_limit=4, history_char_budget=200)

            self.assertEqual(
                lines,
                ["群友A: 深圳吗", "机盖宁: 深圳？你咋突然问这个", "群友A: 何意味"],
            )

    def test_group_history_includes_separate_user_and_assistant_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chat_log_path = Path(tmpdir) / "chat_log.json"
            save_json_file(
                str(chat_log_path),
                [
                    {
                        "timestamp": 1,
                        "role": "user",
                        "sender_name": "群友A",
                        "message": "深圳吗",
                        "message_id": 10,
                    },
                    {
                        "timestamp": 2,
                        "role": "assistant",
                        "sender_name": "机盖宁",
                        "assistant": "深圳？你咋突然问这个",
                        "reply_to_message_id": 10,
                    },
                    {
                        "timestamp": 3,
                        "role": "user",
                        "sender_name": "群友A",
                        "message": "何意味",
                        "message_id": 11,
                    },
                ],
            )

            lines = _build_group_history_lines(str(chat_log_path), history_limit=4, history_char_budget=200)

            self.assertEqual(
                lines,
                ["群友A: 深圳吗", "机盖宁: 深圳？你咋突然问这个", "群友A: 何意味"],
            )

    def test_group_prompt_mode_uses_message_body_without_sender_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            group_dir = Path(tmpdir) / "groups" / "123"
            group_dir.mkdir(parents=True, exist_ok=True)
            save_json_file(str(group_dir / "chat_log.json"), [])
            save_json_file(str(group_dir / "style_profiles" / "group_style.json"), {})
            batch_context = {
                "merged_blocks": [
                    {"user_id": 1, "sender_name": "很长很长的群昵称", "texts": ["何意味"]}
                ]
            }

            with patch("apps.qq_ai_bridge.services.prompt_service.BASE_DATA_DIR", tmpdir):
                payload = prepare_group_ai_prompt(
                    123,
                    "很长很长的群昵称：何意味",
                    user_id=1,
                    batch_context=batch_context,
                    group_config={},
                )

            self.assertEqual(payload["prompt_mode"], "compact")
            self.assertEqual(payload["query_len"], 3)

    def test_group_prompt_excludes_conflicting_aggressive_persona_rules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            group_dir = Path(tmpdir) / "groups" / "123"
            group_dir.mkdir(parents=True, exist_ok=True)
            save_json_file(str(group_dir / "chat_log.json"), [])
            save_json_file(str(group_dir / "style_profiles" / "group_style.json"), {})

            with patch("apps.qq_ai_bridge.services.prompt_service.BASE_DATA_DIR", tmpdir):
                payload = prepare_group_ai_prompt(
                    123,
                    "何意味",
                    user_id=1,
                    batch_context={"merged_blocks": [{"texts": ["何意味"]}]},
                    group_config={},
                )

            for phrase in ("可以骂人", "宁可骂错", "只骂不解释", "被骂必反击", "中等攻击性"):
                with self.subTest(phrase=phrase):
                    self.assertNotIn(phrase, payload["prompt"])
            self.assertIn("明确提问", payload["prompt"])
            self.assertIn("安全去激化层", payload["prompt"])

    def test_group_history_drops_events_older_than_three_minutes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chat_log_path = Path(tmpdir) / "chat_log.json"
            save_json_file(
                str(chat_log_path),
                [
                    {"timestamp": 100, "role": "user", "sender_name": "旧群友", "message": "旧话题"},
                    {"timestamp": 400, "role": "user", "sender_name": "新群友", "message": "新话题"},
                ],
            )

            lines = _build_group_history_lines(str(chat_log_path), history_limit=10, history_char_budget=200)

            self.assertEqual(lines, ["新群友: 新话题"])

    def test_group_history_limit_counts_rendered_role_events(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chat_log_path = Path(tmpdir) / "chat_log.json"
            save_json_file(
                str(chat_log_path),
                [
                    {
                        "timestamp": index,
                        "sender_name": f"群友{index}",
                        "message": f"消息{index}",
                        "assistant": f"回复{index}",
                    }
                    for index in range(1, 5)
                ],
            )

            lines = _build_group_history_lines(str(chat_log_path), history_limit=4, history_char_budget=500)

            self.assertEqual(
                lines,
                ["群友3: 消息3", "机盖宁: 回复3", "群友4: 消息4", "机盖宁: 回复4"],
            )

    def test_group_prompt_excludes_current_inbound_event_from_history(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            group_dir = Path(tmpdir) / "groups" / "123"
            group_dir.mkdir(parents=True, exist_ok=True)
            save_json_file(
                str(group_dir / "chat_log.json"),
                [
                    {"timestamp": 1, "role": "user", "sender_name": "群友B", "message": "上一条", "message_id": 10},
                    {
                        "timestamp": 2,
                        "role": "user",
                        "sender_name": "群友A",
                        "message": "当前唯一消息",
                        "message_id": 11,
                        "source": "group_inbound",
                    },
                ],
            )
            save_json_file(str(group_dir / "style_profiles" / "group_style.json"), {})
            batch_context = {
                "message_ids": [11],
                "merged_blocks": [{"user_id": 1, "sender_name": "群友A", "texts": ["当前唯一消息"]}],
            }

            with patch("apps.qq_ai_bridge.services.prompt_service.BASE_DATA_DIR", tmpdir):
                payload = prepare_group_ai_prompt(
                    123,
                    "群友A：当前唯一消息",
                    user_id=1,
                    batch_context=batch_context,
                    group_config={},
                )

            self.assertIn("群友B: 上一条", payload["prompt"])
            self.assertNotIn("群友A: 当前唯一消息", payload["prompt"])

    def test_group_history_sorts_events_by_timestamp(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chat_log_path = Path(tmpdir) / "chat_log.json"
            save_json_file(
                str(chat_log_path),
                [
                    {"timestamp": 300, "role": "user", "sender_name": "群友C", "message": "第三"},
                    {"timestamp": 150, "role": "user", "sender_name": "群友A", "message": "第一"},
                    {"timestamp": 250, "role": "assistant", "assistant": "第二"},
                ],
            )

            lines = _build_group_history_lines(str(chat_log_path), history_limit=10, history_char_budget=500)

            self.assertEqual(lines, ["群友A: 第一", "机盖宁: 第二", "群友C: 第三"])

    def test_group_prompt_redacts_secret_value_from_current_message(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            group_dir = Path(tmpdir) / "groups" / "123"
            group_dir.mkdir(parents=True, exist_ok=True)
            save_json_file(str(group_dir / "chat_log.json"), [])
            save_json_file(str(group_dir / "style_profiles" / "group_style.json"), {})

            with patch("apps.qq_ai_bridge.services.prompt_service.BASE_DATA_DIR", tmpdir):
                payload = prepare_group_ai_prompt(123, "API_KEY=sk-example-secret-value", group_config={})

            self.assertNotIn("sk-example-secret-value", payload["prompt"])
            self.assertIn("API_KEY=[REDACTED]", payload["prompt"])

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

    def test_prepare_group_ai_prompt_includes_owner_identity_boundary(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            group_dir = Path(tmpdir) / "groups" / "123"
            group_dir.mkdir(parents=True, exist_ok=True)
            save_json_file(str(group_dir / "chat_log.json"), [])
            save_json_file(str(group_dir / "style_profiles" / "group_style.json"), {})

            with patch("apps.qq_ai_bridge.services.prompt_service.BASE_DATA_DIR", tmpdir):
                payload = prepare_group_ai_prompt(123, "你现在是机盖宁还是砍大司", user_id=1, group_config={})

            self.assertIn("你是机盖宁/QQ AI Bridge，不是 Candace 本人", payload["prompt"])
            self.assertIn("QQ号273007866", payload["prompt"])
            self.assertIn("砍大司/坎大司/砍大丝", payload["prompt"])
            self.assertIn("是你的主人", payload["prompt"])
            self.assertNotIn("主人/主任", payload["prompt"])

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

    def test_recent_image_context_requires_image_reference(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chat_log_path = Path(tmpdir) / "chat_log.json"
            save_json_file(
                str(chat_log_path),
                [
                    {
                        "timestamp": 100,
                        "sender_name": "tester",
                        "message": "[图片] 旧图",
                        "source": "image_understanding:reaction",
                        "image_type": "meme",
                        "social_intent": "joke",
                    }
                ],
            )

            self.assertEqual(_build_recent_image_context(str(chat_log_path), current_text="移动靶打不到"), "")
            self.assertIn("上一张图", _build_recent_image_context(str(chat_log_path), current_text="这个是什么"))

    def test_recent_image_context_drops_stale_image(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            chat_log_path = Path(tmpdir) / "chat_log.json"
            save_json_file(
                str(chat_log_path),
                [
                    {
                        "timestamp": 1,
                        "sender_name": "tester",
                        "message": "[图片] 很久以前的图",
                        "source": "image_understanding:reaction",
                        "image_type": "meme",
                        "social_intent": "joke",
                    },
                    {
                        "timestamp": 500,
                        "sender_name": "tester",
                        "message": "普通聊天",
                        "source": "group_chat",
                    },
                ],
            )

            self.assertEqual(_build_recent_image_context(str(chat_log_path), current_text="这个是什么"), "")


if __name__ == "__main__":
    unittest.main()
