import os
import sys
import tempfile
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.adapters.admin_ui import (
    _log_file_meta,
    _normalize_strategy_payload,
    BRIDGE_LOG_PATH,
    mask_sensitive,
    parse_log_line,
    parse_multi_filter_values,
    tail_lines,
)


class AdminConsoleHelpersTest(unittest.TestCase):
    def test_parse_vocat_log_line(self):
        entry = parse_log_line("[VOCAT] poll deliver command_id=abc123 type=tts queue_size=2")

        self.assertEqual(entry["category"], "vocat")
        self.assertEqual(entry["level"], "info")
        self.assertEqual(entry["fields"]["command_id"], "abc123")
        self.assertEqual(entry["fields"]["queue_size"], "2")

    def test_parse_python_dict_fields(self):
        entry = parse_log_line(
            "[VOCAT] ack command_id=abc123 result={'ok': True, 'removed': 1, 'queue_size': 0}"
        )

        self.assertEqual(entry["category"], "vocat")
        self.assertEqual(entry["fields"]["command_id"], "abc123")
        self.assertEqual(entry["fields"]["queue_size"], "0")

    def test_parse_group_fields(self):
        entry = parse_log_line("[WEBHOOK] recv group group_id=810938203 user_id=123 nick='Candace' text='hello'")

        self.assertEqual(entry["category"], "group")
        self.assertEqual(entry["fields"]["group_id"], "810938203")
        self.assertEqual(entry["fields"]["user_id"], "123")
        self.assertEqual(entry["fields"]["nick"], "Candace")
        self.assertEqual(entry["fields"]["text"], "hello")

    def test_mask_sensitive_values(self):
        masked = mask_sensitive(
            "Authorization: Bearer abc.def token=secret access_token=napcat KIMI_API_KEY=sk-test"
        )

        self.assertNotIn("abc.def", masked)
        self.assertNotIn("secret", masked)
        self.assertNotIn("napcat", masked)
        self.assertNotIn("sk-test", masked)
        self.assertIn("[MASKED]", masked)

    def test_parse_multi_filter_values(self):
        values = parse_multi_filter_values(["group,vocat", "private"], {"group", "vocat", "private"})

        self.assertEqual(values, {"group", "vocat", "private"})
        self.assertEqual(parse_multi_filter_values(["group,all"], {"group", "vocat"}), set())
        self.assertEqual(parse_multi_filter_values(["unknown"], {"group", "vocat"}), set())

    def test_tail_lines_clamps_limit(self):
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", delete=False) as fp:
            path = fp.name
            for idx in range(1105):
                fp.write(f"line-{idx}\n")
        try:
            lines = tail_lines(path, 5000)
        finally:
            os.unlink(path)

        self.assertEqual(len(lines), 1000)
        self.assertEqual(lines[0], "line-105")
        self.assertEqual(lines[-1], "line-1104")

    def test_log_file_meta_exposes_size_and_mtime_keys(self):
        meta = _log_file_meta()

        self.assertIn("mtime", meta)
        self.assertIn("size", meta)
        self.assertEqual(str(BRIDGE_LOG_PATH), str(BRIDGE_LOG_PATH.resolve()))

    def test_normalize_strategy_payload_rejects_invalid_probability(self):
        with self.assertRaises(ValueError):
            _normalize_strategy_payload({"reply_probability": 2})

    def test_normalize_strategy_payload_preserves_valid_values(self):
        strategy = _normalize_strategy_payload(
            {
                "reply_probability": 0.6,
                "silence_probability": 0.3,
                "reaction_probability": 0.1,
                "delay_min_ms": 500,
                "delay_max_ms": 4000,
                "context_window_sec": 8,
                "require_mention_for_reply": True,
                "cooldown_sec": 5,
            }
        )

        self.assertEqual(strategy["reply_probability"], 0.6)
        self.assertEqual(strategy["delay_max_ms"], 4000)
        self.assertTrue(strategy["require_mention_for_reply"])


if __name__ == "__main__":
    unittest.main()
