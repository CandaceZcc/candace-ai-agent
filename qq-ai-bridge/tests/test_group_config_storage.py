import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, "qq-ai-bridge")

from storage_utils import is_group_whitelisted, load_group_config, load_group_config_store, save_group_config_store


class GroupConfigStorageTests(unittest.TestCase):
    def test_missing_group_is_not_whitelisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "groups.json")
            self.assertFalse(is_group_whitelisted(config_path, 123456))

    def test_existing_group_requires_explicit_enable(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "groups.json")
            save_group_config_store(
                config_path,
                {
                    "default": {"reply_all_messages": False},
                    "123456": {"name": "测试群"},
                },
            )
            self.assertFalse(is_group_whitelisted(config_path, 123456))

    def test_explicitly_enabled_group_is_whitelisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "groups.json")
            save_group_config_store(
                config_path,
                {
                    "default": {"reply_all_messages": False},
                    "123456": {"name": "测试群", "enabled": True},
                },
            )
            self.assertTrue(is_group_whitelisted(config_path, 123456))

    def test_disabled_or_ignored_group_is_not_whitelisted(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "groups.json")
            save_group_config_store(
                config_path,
                {
                    "default": {"reply_all_messages": False},
                    "123456": {"enabled": False},
                    "654321": {"ignore": True},
                },
            )
            self.assertFalse(is_group_whitelisted(config_path, 123456))
            self.assertFalse(is_group_whitelisted(config_path, 654321))

    def test_load_group_config_merges_default_values(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "groups.json")
            save_group_config_store(
                config_path,
                {
                    "default": {"reply_all_messages": False, "enable_vision": True},
                    "123456": {"name": "测试群", "reply_all_messages": True},
                },
            )
            cfg = load_group_config(config_path, 123456)
            self.assertEqual(cfg["name"], "测试群")
            self.assertTrue(cfg["reply_all_messages"])
            self.assertTrue(cfg["enable_vision"])

    def test_store_loader_normalizes_default_section(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            config_path = os.path.join(temp_dir, "groups.json")
            with open(config_path, "w", encoding="utf-8") as file_obj:
                json.dump({"default": {"bot_can_reply": False}}, file_obj)

            store = load_group_config_store(config_path)
            self.assertIn("enable_vision", store["default"])
            self.assertFalse(store["default"]["bot_can_reply"])


if __name__ == "__main__":
    unittest.main()
