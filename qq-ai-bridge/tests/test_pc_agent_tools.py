import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")


class PcAgentToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_returns_small_structured_result(self):
        from shared.ai.pc_agent_tools import pc_agent_status

        with patch(
            "shared.ai.pc_agent_tools.request_browser_action",
            return_value={"status": "ok", "data": {"status": "ok", "page_title": "Home"}},
        ):
            result = await pc_agent_status()

        self.assertTrue(result.ok)
        self.assertEqual(result.action, "pc_agent_status")
        self.assertIn("ok", result.message)

    async def test_screenshot_redacts_local_path_from_model_output(self):
        from shared.ai.pc_agent_tools import pc_capture_screen

        with patch(
            "shared.ai.pc_agent_tools.request_browser_action",
            return_value={"status": "ok", "data": {"path": "/tmp/private-shot.png"}},
        ):
            result = await pc_capture_screen()

        self.assertTrue(result.ok)
        self.assertNotIn("/tmp/private-shot.png", result.message)
        self.assertNotIn("/tmp/private-shot.png", repr(result))

    async def test_open_url_rejects_non_http_schemes(self):
        from shared.ai.pc_agent_tools import pc_open_http_url

        with patch("shared.ai.pc_agent_tools.request_browser_action") as mock_request:
            result = await pc_open_http_url("file:///etc/passwd")

        self.assertFalse(result.ok)
        self.assertEqual(result.action, "pc_open_http_url")
        mock_request.assert_not_called()

    async def test_action_times_out(self):
        from shared.ai.pc_agent_tools import pc_open_http_url

        with patch(
            "shared.ai.pc_agent_tools.request_browser_action",
            return_value={"status": "error", "error_code": "timeout", "message": "slow"},
        ):
            result = await pc_open_http_url("https://example.com")

        self.assertFalse(result.ok)
        self.assertIn("timed out", result.message)

    async def test_unavailable_service_returns_typed_error(self):
        from shared.ai.pc_agent_tools import pc_agent_status

        with patch(
            "shared.ai.pc_agent_tools.request_browser_action",
            return_value={"status": "error", "error_code": "agent_unreachable"},
        ):
            result = await pc_agent_status()

        self.assertFalse(result.ok)
        self.assertIn("unreachable", result.message)

    async def test_high_impact_action_requires_approval(self):
        from shared.ai.pc_agent_tools import pc_browser_click_text

        with patch("shared.ai.pc_agent_tools.request_browser_action") as mock_request:
            result = await pc_browser_click_text("Submit payment")

        self.assertFalse(result.ok)
        self.assertTrue(result.needs_approval)
        self.assertIn("approval", result.approval_reason)
        mock_request.assert_not_called()

    async def test_login_and_security_actions_require_approval(self):
        from shared.ai.pc_agent_tools import pc_browser_click_text

        with patch("shared.ai.pc_agent_tools.request_browser_action") as mock_request:
            for target in ("Sign in", "登录", "Ignore security warning"):
                with self.subTest(target=target):
                    result = await pc_browser_click_text(target)
                    self.assertFalse(result.ok)
                    self.assertTrue(result.needs_approval)

        mock_request.assert_not_called()

    async def test_tool_never_forwards_environment_or_secret_headers(self):
        from shared.ai.pc_agent_tools import pc_browser_inspect

        with patch(
            "shared.ai.pc_agent_tools.request_browser_action",
            return_value={"status": "ok", "data": {"text": "visible page"}},
        ) as mock_request:
            await pc_browser_inspect()

        _action, params = mock_request.call_args.args[:2]
        self.assertNotIn("headers", params)
        self.assertNotIn("env", params)

    def test_agent_registry_resolves_pc_tools(self):
        from shared.ai.agent_provider import ProviderCapabilities
        from shared.ai.agent_tools import resolve_agent_tools

        tools = resolve_agent_tools(
            ("pc_agent_status", "pc_open_http_url", "pc_capture_screen"),
            ProviderCapabilities(
                responses=True,
                function_tools=True,
                hosted_web_search=False,
                builtin_computer=False,
                openai_trace_export=False,
                verified=True,
            ),
        )

        self.assertEqual(len(tools), 3)


if __name__ == "__main__":
    unittest.main()
