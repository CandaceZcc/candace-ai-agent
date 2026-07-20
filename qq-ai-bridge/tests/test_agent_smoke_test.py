import io
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "qq-ai-bridge")

from shared.ai.agent_runtime import AgentRunResult


class AgentSmokeTestTests(unittest.TestCase):
    def test_config_only_requires_no_runtime_call(self):
        from scripts import agent_smoke_test

        with patch("scripts.agent_smoke_test.AgentRuntime") as mock_runtime:
            output = io.StringIO()
            with redirect_stdout(output):
                code = agent_smoke_test.main(["--config-only"])

        self.assertEqual(code, 0)
        self.assertIn("provider", output.getvalue())
        mock_runtime.assert_not_called()

    def test_text_uses_fake_runtime_and_reports_usage_shape(self):
        from scripts import agent_smoke_test

        runtime = MagicMock()
        runtime.run = AsyncMock(
            return_value=AgentRunResult(
                ok=True,
                output_text="OK",
                provider="responses_proxy",
                model="gpt-5.6",
                tool_names=(),
            )
        )
        with patch("scripts.agent_smoke_test.AgentRuntime", return_value=runtime):
            output = io.StringIO()
            with redirect_stdout(output):
                code = agent_smoke_test.main(["--text", "只回复 OK"])

        self.assertEqual(code, 0)
        self.assertIn("responses_proxy", output.getvalue())
        self.assertIn("latency_ms", output.getvalue())
        self.assertIn("input_tokens", output.getvalue())
        self.assertIn("output_tokens", output.getvalue())

    def test_web_search_requires_billable_acceptance(self):
        from scripts import agent_smoke_test

        with patch("scripts.agent_smoke_test.AgentRuntime") as mock_runtime:
            output = io.StringIO()
            with redirect_stdout(output):
                code = agent_smoke_test.main(["--web-search", "OpenAI 当前 API 文档首页标题"])

        self.assertEqual(code, 2)
        self.assertIn("accept-billable-probe", output.getvalue())
        mock_runtime.assert_not_called()


if __name__ == "__main__":
    unittest.main()
