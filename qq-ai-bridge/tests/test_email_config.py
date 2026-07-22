import importlib
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")


EMAIL_ENV_NAMES = (
    "EMAIL_AGENT_ENABLED",
    "EMAIL_IMAP_HOST",
    "EMAIL_IMAP_PORT",
    "EMAIL_IMAP_USERNAME",
    "EMAIL_IMAP_PASSWORD",
    "EMAIL_IMAP_MAILBOX",
    "EMAIL_DAILY_DIGEST_ENABLED",
    "EMAIL_DAILY_DIGEST_TIME",
    "EMAIL_WEEKLY_DIGEST_ENABLED",
    "EMAIL_WEEKLY_DIGEST_DAY",
    "EMAIL_WEEKLY_DIGEST_TIME",
    "EMAIL_SUMMARY_MODEL",
    "EMAIL_MAX_RANGE_DAYS",
    "EMAIL_MAX_MESSAGES_PER_RUN",
    "EMAIL_MAX_BODY_CHARS",
    "EMAIL_MAX_TOTAL_CHARS",
    "EMAIL_ARCHIVE_RETENTION_DAYS",
    "EMAIL_IMAP_TIMEOUT_SECONDS",
)


def reload_settings_with(env: dict[str, str]):
    import apps.qq_ai_bridge.config.settings as settings

    clean_env = {name: "" for name in EMAIL_ENV_NAMES}
    clean_env.update(env)
    with patch.dict(os.environ, clean_env, clear=False):
        return importlib.reload(settings)


class EmailConfigTests(unittest.TestCase):
    def tearDown(self):
        import apps.qq_ai_bridge.config.settings as settings

        importlib.reload(settings)

    def test_email_agent_is_disabled_by_default(self):
        settings = reload_settings_with({})

        self.assertFalse(settings.EMAIL_AGENT_ENABLED)
        self.assertFalse(settings.EMAIL_MONITOR_ENABLED)
        self.assertFalse(settings.EMAIL_IMMEDIATE_PUSH_ENABLED)
        self.assertFalse(settings.EMAIL_DIGEST_PUSH_ENABLED)
        self.assertTrue(settings.EMAIL_SHADOW_MODE)

    def test_email_automation_defaults_are_safe(self):
        settings = reload_settings_with({})

        self.assertEqual(settings.EMAIL_POLL_INTERVAL_SECONDS, 300)
        self.assertEqual(settings.EMAIL_DIGEST_TIMES, ("12:30", "20:30"))
        self.assertTrue(settings.EMAIL_PROFILE_PATH.endswith("profile.json"))
        self.assertTrue(settings.EMAIL_FEEDBACK_PATH.endswith("learned-feedback.json"))
        self.assertTrue(settings.EMAIL_AUTOMATION_STATE_PATH.endswith("automation-state.json"))

    def test_default_imap_endpoint_is_tls_port_993(self):
        settings = reload_settings_with({})

        self.assertEqual(settings.EMAIL_IMAP_HOST, "imap.exmail.qq.com")
        self.assertEqual(settings.EMAIL_IMAP_PORT, 993)

    def test_enabled_agent_requires_username_and_password(self):
        settings = reload_settings_with({"EMAIL_AGENT_ENABLED": "true"})

        errors = "\n".join(settings.validate_email_settings())
        self.assertIn("EMAIL_IMAP_USERNAME", errors)
        self.assertIn("EMAIL_IMAP_PASSWORD", errors)

    def test_email_automation_requires_owner_qq(self):
        settings = reload_settings_with(
            {
                "EMAIL_MONITOR_ENABLED": "true",
                "OWNER_QQ": "0",
            }
        )

        self.assertIn("OWNER_QQ", "\n".join(settings.validate_email_settings()))

    def test_invalid_digest_times_disable_digest_push_only(self):
        settings = reload_settings_with(
            {
                "EMAIL_AGENT_ENABLED": "true",
                "EMAIL_IMAP_USERNAME": "student@example.invalid",
                "EMAIL_IMAP_PASSWORD": "test-password",
                "EMAIL_DIGEST_PUSH_ENABLED": "true",
                "EMAIL_DIGEST_TIMES": "12:30,25:90",
            }
        )

        self.assertTrue(settings.EMAIL_AGENT_ENABLED)
        self.assertFalse(settings.EMAIL_DIGEST_PUSH_ENABLED)
        self.assertIn("EMAIL_DIGEST_TIMES", "\n".join(settings.validate_email_settings()))

    def test_digest_times_are_normalized_and_deduplicated(self):
        settings = reload_settings_with(
            {
                "EMAIL_DIGEST_TIMES": "20:30, 12:30,20:30",
            }
        )

        self.assertEqual(settings.EMAIL_DIGEST_TIMES, ("12:30", "20:30"))

    def test_poll_interval_has_safe_bounds(self):
        settings = reload_settings_with({"EMAIL_POLL_INTERVAL_SECONDS": "99999"})
        self.assertEqual(settings.EMAIL_POLL_INTERVAL_SECONDS, 3600)

        settings = reload_settings_with({"EMAIL_POLL_INTERVAL_SECONDS": "1"})
        self.assertEqual(settings.EMAIL_POLL_INTERVAL_SECONDS, 60)

    def test_limits_have_safe_caps(self):
        settings = reload_settings_with(
            {
                "EMAIL_MAX_RANGE_DAYS": "999",
                "EMAIL_MAX_MESSAGES_PER_RUN": "9999",
                "EMAIL_MAX_BODY_CHARS": "9999999",
                "EMAIL_MAX_TOTAL_CHARS": "99999999",
                "EMAIL_IMAP_TIMEOUT_SECONDS": "9999",
            }
        )

        self.assertEqual(settings.EMAIL_MAX_RANGE_DAYS, 366)
        self.assertEqual(settings.EMAIL_MAX_MESSAGES_PER_RUN, 500)
        self.assertEqual(settings.EMAIL_MAX_BODY_CHARS, 100000)
        self.assertEqual(settings.EMAIL_MAX_TOTAL_CHARS, 1000000)
        self.assertEqual(settings.EMAIL_IMAP_TIMEOUT_SECONDS, 120)

    def test_config_summary_redacts_email_and_password(self):
        settings = reload_settings_with(
            {
                "EMAIL_IMAP_USERNAME": "private@example.invalid",
                "EMAIL_IMAP_PASSWORD": "super-secret-password",
            }
        )

        summary_text = repr(settings.email_config_summary())
        self.assertNotIn("private@example.invalid", summary_text)
        self.assertNotIn("super-secret-password", summary_text)
        self.assertEqual(settings.email_config_summary()["secrets"]["username"], "set")
        self.assertEqual(settings.email_config_summary()["secrets"]["password"], "set")

    def test_config_summary_exposes_only_safe_automation_state(self):
        settings = reload_settings_with(
            {
                "EMAIL_MONITOR_ENABLED": "true",
                "EMAIL_SHADOW_MODE": "true",
                "EMAIL_DIGEST_TIMES": "12:30,20:30",
            }
        )

        summary = settings.email_config_summary()
        self.assertTrue(summary["automation"]["monitor_enabled"])
        self.assertTrue(summary["automation"]["shadow_mode"])
        self.assertEqual(summary["automation"]["digest_times"], ["12:30", "20:30"])


if __name__ == "__main__":
    unittest.main()
