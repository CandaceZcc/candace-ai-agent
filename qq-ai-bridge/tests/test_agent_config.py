import importlib
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")


AGENT_ENV_NAMES = (
    "AGENT_RUNTIME_ENABLED",
    "AGENT_PROVIDER",
    "OPENAI_API_KEY",
    "OPENAI_AGENT_MODEL",
    "OPENAI_HOSTED_WEB_SEARCH_ENABLED",
    "OPENAI_COMPUTER_USE_ENABLED",
    "RESPONSES_PROXY_API_KEY",
    "RESPONSES_PROXY_BASE_URL",
    "RESPONSES_PROXY_MODEL",
    "RESPONSES_PROXY_TEXT_VERIFIED",
    "RESPONSES_PROXY_WEB_SEARCH_VERIFIED",
    "RESPONSES_PROXY_COMPUTER_VERIFIED",
    "AGENT_MODEL_REASONING_EFFORT",
    "AGENT_DISABLE_RESPONSE_STORAGE",
    "CHAT_COMPATIBLE_API_KEY",
    "CHAT_COMPATIBLE_BASE_URL",
    "CHAT_COMPATIBLE_MODEL",
    "AGENT_PROVIDER_CAPABILITY_STRICT",
    "AGENT_MAX_TURNS",
    "AGENT_MAX_TOOL_CALLS",
    "AGENT_RUN_TIMEOUT_SECONDS",
    "AGENT_TRACE_EXPORT_ENABLED",
    "AGENT_FALLBACK_TO_LEGACY",
)


def reload_settings_with(env: dict[str, str]):
    import apps.qq_ai_bridge.config.settings as settings

    clean_env = {name: "" for name in AGENT_ENV_NAMES}
    clean_env.update(env)
    with patch.dict(os.environ, clean_env, clear=False):
        return importlib.reload(settings)


class AgentConfigTests(unittest.TestCase):
    def tearDown(self):
        import apps.qq_ai_bridge.config.settings as settings

        importlib.reload(settings)

    def test_runtime_is_disabled_by_default(self):
        settings = reload_settings_with({})

        self.assertFalse(settings.AGENT_RUNTIME_ENABLED)
        self.assertEqual(settings.validate_agent_settings(), [])

    def test_provider_defaults_to_openai(self):
        settings = reload_settings_with({})

        self.assertEqual(settings.AGENT_PROVIDER, "openai")
        self.assertEqual(settings.AGENT_PROVIDER_VALUES, {"openai", "responses_proxy", "chat_compatible"})

    def test_responses_proxy_requires_base_url_key_and_model(self):
        settings = reload_settings_with(
            {
                "AGENT_RUNTIME_ENABLED": "true",
                "AGENT_PROVIDER": "responses_proxy",
            }
        )

        errors = "\n".join(settings.validate_agent_settings())
        self.assertIn("RESPONSES_PROXY_BASE_URL", errors)
        self.assertIn("RESPONSES_PROXY_API_KEY", errors)
        self.assertIn("RESPONSES_PROXY_MODEL", errors)

    def test_strict_responses_proxy_requires_text_verification(self):
        settings = reload_settings_with(
            {
                "AGENT_RUNTIME_ENABLED": "true",
                "AGENT_PROVIDER": "responses_proxy",
                "RESPONSES_PROXY_BASE_URL": "https://proxy.example/v1",
                "RESPONSES_PROXY_API_KEY": "sk-proxy-secret",
                "RESPONSES_PROXY_MODEL": "gpt-5.6",
                "AGENT_PROVIDER_CAPABILITY_STRICT": "true",
            }
        )

        errors = "\n".join(settings.validate_agent_settings())
        self.assertIn("RESPONSES_PROXY_TEXT_VERIFIED", errors)

    def test_responses_proxy_rejects_unverified_hosted_capabilities(self):
        settings = reload_settings_with(
            {
                "AGENT_RUNTIME_ENABLED": "true",
                "AGENT_PROVIDER": "responses_proxy",
                "RESPONSES_PROXY_BASE_URL": "https://proxy.example/v1",
                "RESPONSES_PROXY_API_KEY": "sk-proxy-secret",
                "RESPONSES_PROXY_MODEL": "gpt-5.6",
                "RESPONSES_PROXY_TEXT_VERIFIED": "true",
                "OPENAI_HOSTED_WEB_SEARCH_ENABLED": "true",
                "OPENAI_COMPUTER_USE_ENABLED": "true",
            }
        )

        errors = "\n".join(settings.validate_agent_settings())
        self.assertIn("RESPONSES_PROXY_WEB_SEARCH_VERIFIED", errors)
        self.assertIn("RESPONSES_PROXY_COMPUTER_VERIFIED", errors)

    def test_proxy_verification_flags_are_visible_in_redacted_summary(self):
        settings = reload_settings_with(
            {
                "RESPONSES_PROXY_TEXT_VERIFIED": "true",
                "RESPONSES_PROXY_WEB_SEARCH_VERIFIED": "true",
                "RESPONSES_PROXY_COMPUTER_VERIFIED": "false",
            }
        )

        verification = settings.agent_config_summary()["proxy_verification"]
        self.assertTrue(verification["text"])
        self.assertTrue(verification["web_search"])
        self.assertFalse(verification["computer"])

    def test_model_settings_support_high_reasoning_and_disabled_storage(self):
        settings = reload_settings_with(
            {
                "AGENT_MODEL_REASONING_EFFORT": "high",
                "AGENT_DISABLE_RESPONSE_STORAGE": "true",
            }
        )

        self.assertEqual(settings.AGENT_MODEL_REASONING_EFFORT, "high")
        self.assertTrue(settings.AGENT_DISABLE_RESPONSE_STORAGE)
        summary = settings.agent_config_summary()
        self.assertEqual(summary["model_settings"]["reasoning_effort"], "high")
        self.assertTrue(summary["model_settings"]["response_storage_disabled"])

    def test_invalid_reasoning_effort_is_rejected(self):
        settings = reload_settings_with({"AGENT_MODEL_REASONING_EFFORT": "ultra"})

        errors = "\n".join(settings.validate_agent_settings())
        self.assertIn("AGENT_MODEL_REASONING_EFFORT", errors)

    def test_chat_compatible_rejects_hosted_web_search(self):
        settings = reload_settings_with(
            {
                "AGENT_RUNTIME_ENABLED": "true",
                "AGENT_PROVIDER": "chat_compatible",
                "CHAT_COMPATIBLE_BASE_URL": "https://chat.example/v1",
                "CHAT_COMPATIBLE_API_KEY": "sk-chat-secret",
                "CHAT_COMPATIBLE_MODEL": "deepseek-v4",
                "OPENAI_HOSTED_WEB_SEARCH_ENABLED": "true",
            }
        )

        errors = "\n".join(settings.validate_agent_settings())
        self.assertIn("hosted web search", errors)

    def test_chat_compatible_rejects_builtin_computer_use(self):
        settings = reload_settings_with(
            {
                "AGENT_RUNTIME_ENABLED": "true",
                "AGENT_PROVIDER": "chat_compatible",
                "CHAT_COMPATIBLE_BASE_URL": "https://chat.example/v1",
                "CHAT_COMPATIBLE_API_KEY": "sk-chat-secret",
                "CHAT_COMPATIBLE_MODEL": "deepseek-v4",
                "OPENAI_COMPUTER_USE_ENABLED": "true",
            }
        )

        errors = "\n".join(settings.validate_agent_settings())
        self.assertIn("built-in computer", errors)

    def test_limits_reject_zero_or_negative_values(self):
        settings = reload_settings_with(
            {
                "AGENT_MAX_TURNS": "0",
                "AGENT_MAX_TOOL_CALLS": "-1",
                "AGENT_RUN_TIMEOUT_SECONDS": "0",
            }
        )

        errors = "\n".join(settings.validate_agent_settings())
        self.assertIn("AGENT_MAX_TURNS", errors)
        self.assertIn("AGENT_MAX_TOOL_CALLS", errors)
        self.assertIn("AGENT_RUN_TIMEOUT_SECONDS", errors)

    def test_secret_values_are_not_returned_by_config_summary(self):
        settings = reload_settings_with(
            {
                "AGENT_RUNTIME_ENABLED": "true",
                "OPENAI_API_KEY": "sk-openai-secret",
                "RESPONSES_PROXY_API_KEY": "sk-proxy-secret",
                "CHAT_COMPATIBLE_API_KEY": "sk-chat-secret",
                "RESPONSES_PROXY_BASE_URL": "https://proxy.example/v1",
                "RESPONSES_PROXY_MODEL": "gpt-5.6",
                "CHAT_COMPATIBLE_BASE_URL": "https://chat.example/v1",
                "CHAT_COMPATIBLE_MODEL": "deepseek-v4",
            }
        )

        summary_text = repr(settings.agent_config_summary())
        self.assertNotIn("sk-openai-secret", summary_text)
        self.assertNotIn("sk-proxy-secret", summary_text)
        self.assertNotIn("sk-chat-secret", summary_text)
        self.assertIn("openai_api_key", summary_text)
        self.assertIn("set", summary_text)


if __name__ == "__main__":
    unittest.main()
