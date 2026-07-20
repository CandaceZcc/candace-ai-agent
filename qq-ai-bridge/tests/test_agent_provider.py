import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "qq-ai-bridge")


class AgentProviderTests(unittest.TestCase):
    def test_official_openai_uses_responses_model(self):
        from shared.ai import agent_provider

        with (
            patch.object(agent_provider, "AsyncOpenAI") as mock_client,
            patch.object(agent_provider, "OpenAIResponsesModel") as mock_responses_model,
            patch.object(agent_provider, "set_tracing_disabled") as mock_tracing,
            patch.multiple(
                agent_provider,
                OPENAI_API_KEY="sk-openai",
                OPENAI_AGENT_MODEL="gpt-5.6",
                OPENAI_HOSTED_WEB_SEARCH_ENABLED=True,
                OPENAI_COMPUTER_USE_ENABLED=True,
                AGENT_TRACE_EXPORT_ENABLED=False,
            ),
        ):
            mock_client.return_value = MagicMock(name="client")
            mock_responses_model.return_value = MagicMock(name="model")

            binding = agent_provider.build_agent_model_binding(provider="openai")

        mock_client.assert_called_once_with(api_key="sk-openai")
        mock_responses_model.assert_called_once_with(
            model="gpt-5.6",
            openai_client=mock_client.return_value,
        )
        mock_tracing.assert_called_once_with(True)
        self.assertEqual(binding.provider, "openai")
        self.assertTrue(binding.capabilities.responses)
        self.assertTrue(binding.capabilities.hosted_web_search)
        self.assertTrue(binding.capabilities.builtin_computer)

    def test_responses_proxy_uses_custom_client_and_responses_model(self):
        from shared.ai import agent_provider

        with (
            patch.object(agent_provider, "AsyncOpenAI") as mock_client,
            patch.object(agent_provider, "OpenAIResponsesModel") as mock_responses_model,
            patch.object(agent_provider, "set_tracing_disabled") as mock_tracing,
            patch.multiple(
                agent_provider,
                RESPONSES_PROXY_API_KEY="sk-proxy",
                RESPONSES_PROXY_BASE_URL="https://proxy.example/v1",
                RESPONSES_PROXY_MODEL="gpt-5.6-proxy",
            ),
        ):
            binding = agent_provider.build_agent_model_binding(provider="responses_proxy")

        mock_client.assert_called_once_with(
            api_key="sk-proxy",
            base_url="https://proxy.example/v1",
        )
        mock_responses_model.assert_called_once_with(
            model="gpt-5.6-proxy",
            openai_client=mock_client.return_value,
        )
        mock_tracing.assert_called_once_with(True)
        self.assertEqual(binding.provider, "responses_proxy")
        self.assertFalse(binding.capabilities.verified)

    def test_chat_compatible_uses_chat_completions_model(self):
        from shared.ai import agent_provider

        with (
            patch.object(agent_provider, "AsyncOpenAI") as mock_client,
            patch.object(agent_provider, "OpenAIChatCompletionsModel") as mock_chat_model,
            patch.object(agent_provider, "set_tracing_disabled") as mock_tracing,
            patch.multiple(
                agent_provider,
                CHAT_COMPATIBLE_API_KEY="sk-chat",
                CHAT_COMPATIBLE_BASE_URL="https://chat.example/v1",
                CHAT_COMPATIBLE_MODEL="deepseek-v4",
            ),
        ):
            binding = agent_provider.build_agent_model_binding(provider="chat_compatible")

        mock_client.assert_called_once_with(
            api_key="sk-chat",
            base_url="https://chat.example/v1",
        )
        mock_chat_model.assert_called_once_with(
            model="deepseek-v4",
            openai_client=mock_client.return_value,
        )
        mock_tracing.assert_called_once_with(True)
        self.assertEqual(binding.provider, "chat_compatible")
        self.assertFalse(binding.capabilities.responses)

    def test_chat_provider_never_reports_hosted_web_search(self):
        from shared.ai import agent_provider

        with (
            patch.object(agent_provider, "AsyncOpenAI"),
            patch.object(agent_provider, "OpenAIChatCompletionsModel"),
            patch.object(agent_provider, "set_tracing_disabled"),
            patch.multiple(
                agent_provider,
                CHAT_COMPATIBLE_API_KEY="sk-chat",
                CHAT_COMPATIBLE_BASE_URL="https://chat.example/v1",
                CHAT_COMPATIBLE_MODEL="deepseek-v4",
                OPENAI_HOSTED_WEB_SEARCH_ENABLED=True,
                OPENAI_COMPUTER_USE_ENABLED=True,
            ),
        ):
            binding = agent_provider.build_agent_model_binding(provider="chat_compatible")

        self.assertFalse(binding.capabilities.hosted_web_search)
        self.assertFalse(binding.capabilities.builtin_computer)

    def test_proxy_capabilities_start_unverified(self):
        from shared.ai import agent_provider

        with (
            patch.object(agent_provider, "AsyncOpenAI"),
            patch.object(agent_provider, "OpenAIResponsesModel"),
            patch.object(agent_provider, "set_tracing_disabled"),
            patch.multiple(
                agent_provider,
                RESPONSES_PROXY_API_KEY="sk-proxy",
                RESPONSES_PROXY_BASE_URL="https://proxy.example/v1",
                RESPONSES_PROXY_MODEL="gpt-5.6-proxy",
                OPENAI_HOSTED_WEB_SEARCH_ENABLED=True,
                OPENAI_COMPUTER_USE_ENABLED=True,
            ),
        ):
            binding = agent_provider.build_agent_model_binding(provider="responses_proxy")

        self.assertTrue(binding.capabilities.responses)
        self.assertTrue(binding.capabilities.function_tools)
        self.assertFalse(binding.capabilities.hosted_web_search)
        self.assertFalse(binding.capabilities.builtin_computer)
        self.assertFalse(binding.capabilities.verified)

    def test_official_provider_does_not_override_base_url(self):
        from shared.ai import agent_provider

        with (
            patch.object(agent_provider, "AsyncOpenAI") as mock_client,
            patch.object(agent_provider, "OpenAIResponsesModel"),
            patch.object(agent_provider, "set_tracing_disabled"),
            patch.multiple(
                agent_provider,
                OPENAI_API_KEY="sk-openai",
                OPENAI_AGENT_MODEL="gpt-5.6",
            ),
        ):
            agent_provider.build_agent_model_binding(provider="openai")

        self.assertNotIn("base_url", mock_client.call_args.kwargs)


if __name__ == "__main__":
    unittest.main()
