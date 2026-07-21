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
        self.assertFalse(settings.EMAIL_DAILY_DIGEST_ENABLED)
        self.assertFalse(settings.EMAIL_WEEKLY_DIGEST_ENABLED)

    def test_default_imap_endpoint_is_tls_port_993(self):
        settings = reload_settings_with({})

        self.assertEqual(settings.EMAIL_IMAP_HOST, "imap.exmail.qq.com")
        self.assertEqual(settings.EMAIL_IMAP_PORT, 993)

    def test_enabled_agent_requires_username_and_password(self):
        settings = reload_settings_with({"EMAIL_AGENT_ENABLED": "true"})

        errors = "\n".join(settings.validate_email_settings())
        self.assertIn("EMAIL_IMAP_USERNAME", errors)
        self.assertIn("EMAIL_IMAP_PASSWORD", errors)

    def test_scheduled_digest_requires_owner_qq(self):
        settings = reload_settings_with(
            {
                "EMAIL_DAILY_DIGEST_ENABLED": "true",
                "OWNER_QQ": "0",
            }
        )

        self.assertIn("OWNER_QQ", "\n".join(settings.validate_email_settings()))

    def test_invalid_daily_time_disables_email_schedule_only(self):
        settings = reload_settings_with(
            {
                "EMAIL_AGENT_ENABLED": "true",
                "EMAIL_IMAP_USERNAME": "student@example.invalid",
                "EMAIL_IMAP_PASSWORD": "test-password",
                "EMAIL_DAILY_DIGEST_ENABLED": "true",
                "EMAIL_DAILY_DIGEST_TIME": "25:90",
            }
        )

        self.assertTrue(settings.EMAIL_AGENT_ENABLED)
        self.assertFalse(settings.EMAIL_DAILY_DIGEST_ENABLED)
        self.assertIn("EMAIL_DAILY_DIGEST_TIME", "\n".join(settings.validate_email_settings()))

    def test_invalid_weekday_is_rejected(self):
        settings = reload_settings_with(
            {
                "EMAIL_WEEKLY_DIGEST_ENABLED": "true",
                "EMAIL_WEEKLY_DIGEST_DAY": "someday",
            }
        )

        self.assertFalse(settings.EMAIL_WEEKLY_DIGEST_ENABLED)
        self.assertIn("EMAIL_WEEKLY_DIGEST_DAY", "\n".join(settings.validate_email_settings()))

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


if __name__ == "__main__":
    unittest.main()
