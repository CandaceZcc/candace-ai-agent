"""群聊时间线捕获和存储回归测试。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.adapters import webhook
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR
from storage_utils import append_group_chat_log, load_json_file


class GroupTimelineTests(unittest.TestCase):
    def _parsed_group_text(self, *, text: str = "普通讨论", message_id: int = 123) -> dict:
        return {
            "type": "text",
            "msg_type": "group",
            "user_id": 10001,
            "group_id": 20002,
            "text": text,
            "is_mentioned": False,
            "raw_message": text,
            "nick": "群友A",
            "timestamp": 1784627000,
            "image_inputs": {"has_image": False, "image_urls": [], "text": text},
            "reply_reference": None,
            "at_targets": [],
            "self_id": 30003,
            "message_id": message_id,
            "trace_id": "timeline-test",
        }

    @patch("apps.qq_ai_bridge.adapters.webhook.finish_trace")
    @patch("apps.qq_ai_bridge.adapters.webhook.add_trace_step")
    @patch("apps.qq_ai_bridge.adapters.webhook.dispatch_skill", return_value=None)
    @patch("apps.qq_ai_bridge.adapters.webhook.append_group_chat_log", create=True)
    @patch("apps.qq_ai_bridge.adapters.webhook.load_group_config")
    def test_dispatch_captures_group_text_before_skill_routing(
        self,
        mock_load_config,
        mock_append,
        _mock_dispatch,
        _mock_trace,
        _mock_finish,
    ):
        mock_load_config.return_value = {
            "enabled": True,
            "ignore": False,
            "capture_all_messages": True,
            "learn_style": False,
        }

        webhook.SkillDispatcher.dispatch(self._parsed_group_text(text="API_KEY=sk-example-secret-value"))

        mock_append.assert_called_once()
        base_dir, group_id, entry = mock_append.call_args.args[:3]
        self.assertEqual(base_dir, BASE_DATA_DIR)
        self.assertEqual(group_id, 20002)
        self.assertEqual(entry["role"], "user")
        self.assertEqual(entry["message"], "API_KEY=[REDACTED]")
        self.assertEqual(entry["message_id"], 123)
        self.assertEqual(entry["source"], "group_inbound")

    @patch("apps.qq_ai_bridge.adapters.webhook.finish_trace")
    @patch("apps.qq_ai_bridge.adapters.webhook.add_trace_step")
    @patch("apps.qq_ai_bridge.adapters.webhook.dispatch_skill", return_value=None)
    @patch("apps.qq_ai_bridge.adapters.webhook.append_group_chat_log", create=True)
    @patch("apps.qq_ai_bridge.adapters.webhook.load_group_config")
    def test_dispatch_does_not_capture_when_capture_all_is_disabled(
        self,
        mock_load_config,
        mock_append,
        _mock_dispatch,
        _mock_trace,
        _mock_finish,
    ):
        mock_load_config.return_value = {
            "enabled": True,
            "ignore": False,
            "capture_all_messages": False,
            "learn_style": False,
        }

        webhook.SkillDispatcher.dispatch(self._parsed_group_text())

        mock_append.assert_not_called()

    @patch("apps.qq_ai_bridge.adapters.webhook.finish_trace")
    @patch("apps.qq_ai_bridge.adapters.webhook.add_trace_step")
    @patch("apps.qq_ai_bridge.adapters.webhook.dispatch_skill", return_value=None)
    @patch("apps.qq_ai_bridge.adapters.webhook.capture_group_style")
    @patch("apps.qq_ai_bridge.adapters.webhook.load_group_config")
    def test_style_capture_uses_configured_base_data_dir(
        self,
        mock_load_config,
        mock_capture_style,
        _mock_dispatch,
        _mock_trace,
        _mock_finish,
    ):
        mock_load_config.return_value = {
            "enabled": True,
            "ignore": False,
            "capture_all_messages": False,
            "learn_style": True,
        }

        webhook.SkillDispatcher.dispatch(self._parsed_group_text(text="API_KEY=sk-example-secret-value"))

        self.assertEqual(mock_capture_style.call_args.args[0], BASE_DATA_DIR)
        self.assertEqual(mock_capture_style.call_args.args[3], "API_KEY=[REDACTED]")

    def test_role_event_with_same_message_id_updates_instead_of_duplicating(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            first = {
                "timestamp": 1,
                "role": "user",
                "sender_name": "群友A",
                "user_id": 10001,
                "message": "[图片]",
                "message_id": 456,
                "source": "group_inbound",
            }
            enriched = {**first, "message": "[图片] 爸爸"}

            append_group_chat_log(tmpdir, 20002, first)
            append_group_chat_log(tmpdir, 20002, enriched)

            path = Path(tmpdir) / "groups" / "20002" / "chat_log.json"
            events = load_json_file(str(path), [])
            self.assertEqual(len(events), 1)
            self.assertEqual(events[0]["message"], "[图片] 爸爸")

    def test_atomic_json_save_preserves_previous_file_when_dump_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "state.json"
            from storage_utils import save_json_file

            save_json_file(str(path), {"version": 1})
            with patch("storage_utils.json.dump", side_effect=RuntimeError("write failed")):
                with self.assertRaises(RuntimeError):
                    save_json_file(str(path), {"version": 2})

            self.assertEqual(load_json_file(str(path), {}), {"version": 1})

    def test_webhook_preview_redacts_secret_values(self):
        self.assertEqual(webhook._preview_text("密码95279527"), "密码[REDACTED]")
        self.assertEqual(webhook._preview_text("token 数量怎么算"), "token 数量怎么算")


if __name__ == "__main__":
    unittest.main()
