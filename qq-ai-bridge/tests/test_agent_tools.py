import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")


def _capabilities(**overrides):
    from shared.ai.agent_provider import ProviderCapabilities

    values = {
        "responses": True,
        "function_tools": True,
        "hosted_web_search": True,
        "builtin_computer": False,
        "openai_trace_export": False,
        "verified": True,
    }
    values.update(overrides)
    return ProviderCapabilities(**values)


class AgentToolsTests(unittest.TestCase):
    def test_web_search_constructed_only_when_enabled_and_supported(self):
        from shared.ai.agent_tools import resolve_agent_tools

        with patch("shared.ai.agent_tools.OPENAI_HOSTED_WEB_SEARCH_ENABLED", True):
            tools = resolve_agent_tools(("web_search",), _capabilities())

        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0].search_context_size, "low")

    def test_proxy_without_verified_search_fails_closed(self):
        from shared.ai.agent_tools import CapabilityUnavailable, resolve_agent_tools

        with patch("shared.ai.agent_tools.OPENAI_HOSTED_WEB_SEARCH_ENABLED", True):
            with self.assertRaises(CapabilityUnavailable):
                resolve_agent_tools(
                    ("web_search",),
                    _capabilities(hosted_web_search=False, verified=False),
                )

    def test_chat_compatible_cannot_construct_web_search(self):
        from shared.ai.agent_tools import CapabilityUnavailable, resolve_agent_tools

        with patch("shared.ai.agent_tools.OPENAI_HOSTED_WEB_SEARCH_ENABLED", True):
            with self.assertRaises(CapabilityUnavailable):
                resolve_agent_tools(("web_search",), _capabilities(responses=False))

    def test_unknown_tool_name_is_rejected(self):
        from shared.ai.agent_tools import CapabilityUnavailable, resolve_agent_tools

        with self.assertRaises(CapabilityUnavailable):
            resolve_agent_tools(("unknown",), _capabilities())

    def test_registry_returns_only_requested_tools(self):
        from shared.ai.agent_tools import resolve_agent_tools

        with patch("shared.ai.agent_tools.OPENAI_HOSTED_WEB_SEARCH_ENABLED", True):
            self.assertEqual(resolve_agent_tools((), _capabilities()), [])
            tools = resolve_agent_tools(("web_search",), _capabilities())

        self.assertEqual(len(tools), 1)

    def test_formats_citations_from_response_items(self):
        from shared.ai.agent_tools import format_response_with_citations

        text = format_response_with_citations(
            "这里是答案。",
            [
                {
                    "type": "message",
                    "content": [
                        {
                            "annotations": [
                                {
                                    "type": "url_citation",
                                    "title": "Docs",
                                    "url": "https://example.com/docs",
                                },
                                {
                                    "type": "url_citation",
                                    "title": "Duplicate",
                                    "url": "https://example.com/docs",
                                },
                            ]
                        }
                    ],
                }
            ],
        )

        self.assertIn("来源：", text)
        self.assertIn("[1] Docs - https://example.com/docs", text)
        self.assertEqual(text.count("https://example.com/docs"), 1)


if __name__ == "__main__":
    unittest.main()
