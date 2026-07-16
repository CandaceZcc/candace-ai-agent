import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, "qq-ai-bridge")

from shared.ai import llm_client
from shared.ai.llm_client import _extract_output_and_usage, _select_llm_backend, call_ai


class LlmClientTests(unittest.TestCase):
    def test_auto_backend_prefers_direct_when_api_key_is_configured(self):
        self.assertEqual(_select_llm_backend("auto", api_key="sk-test"), "direct")
        self.assertEqual(_select_llm_backend("auto", api_key=""), "cli")
        self.assertEqual(_select_llm_backend("cli", api_key="sk-test"), "cli")

    @patch.object(llm_client, "KIMI_MODEL", "deepseek-v4-flash")
    @patch.object(llm_client, "KIMI_BASE_URL", "https://api.deepseek.example/v1")
    @patch.object(llm_client, "KIMI_API_KEY", "sk-test")
    @patch.object(llm_client, "LLM_BACKEND", "direct")
    @patch.object(llm_client.subprocess, "run")
    @patch.object(llm_client, "_HTTP_SESSION")
    def test_call_ai_direct_backend_reuses_http_session(self, mock_session, mock_run):
        response = MagicMock()
        response.json.return_value = {
            "choices": [{"message": {"content": "收到"}}],
            "usage": {"total_tokens": 4},
        }
        mock_session.post.return_value = response

        first = call_ai("第一次", metadata={"user_id": 1})
        second = call_ai("第二次", metadata={"user_id": 1})

        self.assertEqual(first, "收到")
        self.assertEqual(second, "收到")
        self.assertEqual(mock_session.post.call_count, 2)
        self.assertEqual(mock_session.post.call_args.args[0], "https://api.deepseek.example/v1/chat/completions")
        self.assertEqual(mock_session.post.call_args.kwargs["json"]["model"], "deepseek-v4-flash")
        self.assertEqual(
            mock_session.post.call_args.kwargs["headers"]["Authorization"],
            "Bearer sk-test",
        )
        mock_run.assert_not_called()

    @patch.object(llm_client, "KIMI_API_KEY", "sk-test")
    @patch.object(llm_client, "LLM_BACKEND", "direct")
    @patch.object(llm_client, "_HTTP_SESSION")
    def test_call_ai_direct_backend_preserves_message_list(self, mock_session):
        response = MagicMock()
        response.json.return_value = {"choices": [{"message": {"content": "收到"}}]}
        mock_session.post.return_value = response
        messages = [
            {"role": "system", "content": "系统规则"},
            {"role": "user", "content": "执行任务"},
        ]

        result = call_ai(messages)

        self.assertEqual(result, "收到")
        self.assertEqual(mock_session.post.call_args.kwargs["json"]["messages"], messages)

    @patch.object(llm_client, "LLM_BACKEND", "cli")
    @patch.object(llm_client, "_HTTP_SESSION")
    @patch.object(llm_client.subprocess, "run")
    def test_call_ai_cli_backend_keeps_openclaw_compatibility(self, mock_run, mock_session):
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="CLI 回复", stderr="")

        result = call_ai("测试", metadata={"user_id": 1})

        self.assertEqual(result, "CLI 回复")
        mock_run.assert_called_once()
        mock_session.post.assert_not_called()

    @patch.object(llm_client, "LLM_BACKEND", "cli")
    @patch.object(llm_client.subprocess, "run")
    def test_call_ai_cli_backend_serializes_message_list(self, mock_run):
        mock_run.return_value = SimpleNamespace(returncode=0, stdout="CLI 回复", stderr="")
        messages = [
            {"role": "system", "content": "系统规则"},
            {"role": "user", "content": "执行任务"},
        ]

        result = call_ai(messages)

        self.assertEqual(result, "CLI 回复")
        self.assertEqual(
            mock_run.call_args.args[0][1],
            "system: 系统规则\nuser: 执行任务",
        )

    @patch.object(llm_client, "_HTTP_SESSION")
    @patch.object(llm_client.subprocess, "run")
    @patch.object(llm_client, "_acquire_llm_slot", return_value=False)
    def test_call_ai_returns_busy_without_starting_provider(self, _mock_acquire, mock_run, mock_session):
        result = call_ai("测试", metadata={"user_id": 1})

        self.assertEqual(result, "当前模型请求较多，请稍后再试。")
        mock_run.assert_not_called()
        mock_session.post.assert_not_called()

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
