import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.private_admin_service import maybe_handle_private_admin_command


class PrivateAdminServiceTests(unittest.TestCase):
    def test_owner_can_enable_6657_for_one_group(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "groups.json")
            _write_groups(path)
            with patch("apps.qq_ai_bridge.services.private_admin_service.GROUP_CONFIG_PATH", path):
                result = maybe_handle_private_admin_command(
                    273007866,
                    "为哈基米音乐作者群开启6657弹幕",
                )
            with open(path, encoding="utf-8") as fp:
                store = json.load(fp)

        self.assertTrue(result["ok"])
        self.assertTrue(store["810938203"]["enable_6657_barrage"])
        self.assertIn("已开启", result["reply"])
        self.assertEqual(result["updates"], {"enable_6657_barrage": True})

    def test_owner_can_view_6657_group_config(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "groups.json")
            _write_groups(path)
            with patch("apps.qq_ai_bridge.services.private_admin_service.GROUP_CONFIG_PATH", path):
                result = maybe_handle_private_admin_command(
                    273007866,
                    "查看哈基米音乐作者群的6657弹幕配置",
                )

        self.assertTrue(result["ok"])
        self.assertIn("未开启", result["reply"])
        self.assertIn("冷却=240秒", result["reply"])
        self.assertIn("每日上限=20", result["reply"])

    @patch("apps.qq_ai_bridge.services.private_admin_service.sync_6657_barrages_safely")
    @patch("apps.qq_ai_bridge.services.private_admin_service.Barrage6657Store")
    def test_owner_can_sync_6657_library(self, mock_store_class, mock_sync):
        mock_sync.return_value = {
            "ok": True,
            "stats": {"tags": 28, "barrages": 21921, "hot_items": 60, "pages": 220},
        }
        mock_store_class.return_value.get_stats.return_value = {
            "tags": 28,
            "barrages": 21921,
            "hot_snapshots": 60,
        }

        result = maybe_handle_private_admin_command(273007866, "同步6657弹幕库")

        self.assertTrue(result["ok"])
        mock_sync.assert_called_once_with(log=unittest.mock.ANY)
        self.assertIn("21921", result["reply"])
        self.assertIn("28", result["reply"])

    def test_owner_can_view_group_strategy_by_name(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "groups.json")
            _write_groups(path)
            with patch("apps.qq_ai_bridge.services.private_admin_service.GROUP_CONFIG_PATH", path):
                result = maybe_handle_private_admin_command(273007866, "查看哈基米音乐作者群的策略")

        self.assertTrue(result["ok"])
        self.assertIn("哈基米音乐作者群", result["reply"])
        self.assertIn("触发=全局", result["reply"])

    def test_owner_can_update_trigger_and_probabilities(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "groups.json")
            _write_groups(path)
            with patch("apps.qq_ai_bridge.services.private_admin_service.GROUP_CONFIG_PATH", path):
                result = maybe_handle_private_admin_command(
                    273007866,
                    "把哈基米音乐作者群调整为仅艾特，沉默频率0.5，回复频率0.5",
                )
            with open(path, encoding="utf-8") as fp:
                store = json.load(fp)

        self.assertTrue(result["ok"])
        self.assertFalse(store["810938203"]["reply_all_messages"])
        self.assertEqual(store["810938203"]["strategy"]["silence_probability"], 0.5)
        self.assertEqual(store["810938203"]["strategy"]["reply_probability"], 0.5)
        self.assertEqual(store["810938203"]["name"], "哈基米音乐作者群")

    def test_non_owner_is_rejected(self):
        result = maybe_handle_private_admin_command(123, "查看哈基米音乐作者群的策略")

        self.assertFalse(result["ok"])
        self.assertIn("只允许", result["reply"])


def _write_groups(path: str) -> None:
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(
            {
                "default": {"reply_all_messages": False},
                "810938203": {
                    "name": "哈基米音乐作者群",
                    "reply_all_messages": True,
                    "strategy": {
                        "reply_probability": 0.7,
                        "silence_probability": 0.2,
                        "reaction_probability": 0.1,
                    },
                },
            },
            fp,
            ensure_ascii=False,
        )


if __name__ == "__main__":
    unittest.main()
