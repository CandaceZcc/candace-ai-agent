import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from shared.ai.llm_client import _extract_output_and_usage


class LlmClientTests(unittest.TestCase):
    def test_extract_output_keeps_plain_reply(self):
        output, usage = _extract_output_and_usage("收到，测试正常\n")

        self.assertEqual(output, "收到，测试正常")
        self.assertIsNone(usage)

    def test_extract_output_filters_openclaw_plugin_warning_before_reply(self):
        raw = (
            "\x1b[35m[plugins]\x1b[39m \x1b[33mplugins.allow is empty; discovered "
            "non-bundled plugins may auto-load: moonshot "
            "(/home/cancade/.openclaw/npm/projects/openclaw-moonshot-provider/"
            "node_modules/pkg/index.js). "
            "To trust them explicitly, set plugins.allow in openclaw.json (experimental).\x1b[39m\n"
            "收到，测试正常"
        )

        output, usage = _extract_output_and_usage(raw)

        self.assertEqual(output, "收到，测试正常")
        self.assertIsNone(usage)

    def test_extract_output_drops_warning_only_output(self):
        raw = (
            "\x1b[35m[plugins]\x1b[39m \x1b[33mplugins.allow is empty; discovered "
            "non-bundled plugins may auto-load: moonshot "
            "(/home/cancade/.openclaw/npm/projects/openclaw-moonshot-provider/"
            "node_modules/pkg/index.js). "
            "To trust them explicitly, set plugins.allow in openclaw.json (experimental).\x1b[39m"
        )

        output, usage = _extract_output_and_usage(raw)

        self.assertEqual(output, "")
        self.assertIsNone(usage)

    def test_extract_output_preserves_json_usage(self):
        raw = '{"output":"收到","usage":{"prompt_tokens":3,"completion_tokens":1,"total_tokens":4}}'

        output, usage = _extract_output_and_usage(raw)

        self.assertEqual(output, "收到")
        self.assertEqual(usage["total_tokens"], 4)


if __name__ == "__main__":
    unittest.main()
