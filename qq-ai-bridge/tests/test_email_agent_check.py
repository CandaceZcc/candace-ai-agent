import io
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.time_utils import LOCAL_TIMEZONE


class EmailAgentCheckTests(unittest.TestCase):
    def run_main(self, *args):
        from scripts import email_agent_check

        output = io.StringIO()
        with patch("sys.stdout", output):
            exit_code = email_agent_check.main(list(args))
        return exit_code, json.loads(output.getvalue())

    def test_config_masks_identity_and_reports_secret_state(self):
        from scripts import email_agent_check

        summary = {
            "enabled": False,
            "automation": {"shadow_mode": True},
            "secrets": {"username": "set", "password": "set"},
            "validation_errors": [],
        }
        with (
            patch.object(email_agent_check, "EMAIL_IMAP_USERNAME", "private@example.invalid"),
            patch.object(email_agent_check, "email_config_summary", return_value=summary),
        ):
            exit_code, payload = self.run_main("--config")

        self.assertEqual(exit_code, 0)
        serialized = json.dumps(payload)
        self.assertNotIn("private@example.invalid", serialized)
        self.assertEqual(payload["identity"], "p***@***")
        self.assertEqual(payload["config"]["secrets"]["password"], "set")

    def test_config_reports_missing_password_without_prompting(self):
        from scripts import email_agent_check

        summary = {
            "secrets": {"username": "set", "password": "missing"},
            "validation_errors": ["EMAIL_IMAP_PASSWORD is required"],
        }
        with patch.object(email_agent_check, "email_config_summary", return_value=summary):
            _, payload = self.run_main("--config")

        self.assertEqual(payload["config"]["secrets"]["password"], "missing")

    def test_imap_check_uses_read_only_uid_fetch_and_reports_no_content(self):
        from scripts import email_agent_check

        service = MagicMock()
        service.fetch_new.return_value = SimpleNamespace(uid_validity="44", messages=(object(),))
        with patch.object(email_agent_check, "_build_imap_service", return_value=service):
            exit_code, payload = self.run_main("--imap")

        self.assertEqual(exit_code, 0)
        service.fetch_new.assert_called_once_with(last_uid=0, limit=1)
        self.assertEqual(
            payload,
            {"check": "imap", "message_count": 1, "ok": True, "uidvalidity": "44"},
        )

    def test_shadow_report_contains_counts_only(self):
        from scripts import email_agent_check

        store = MagicMock()
        store.pending_analysis.return_value = (object(), object())
        store.pending_digest.return_value = (object(),)
        now = datetime(2026, 7, 21, 12, 0, tzinfo=LOCAL_TIMEZONE)
        with (
            patch.object(email_agent_check, "_build_processing_store", return_value=store),
            patch.object(email_agent_check, "get_now_local", return_value=now),
        ):
            _, payload = self.run_main("--shadow-report")

        self.assertEqual(payload["pending_analysis"], 2)
        self.assertEqual(payload["pending_digest_24h"], 1)
        store.pending_digest.assert_called_once_with(now, lookback_hours=24)

    def test_cleanup_dry_run_reports_count_without_paths(self):
        from scripts import email_agent_check

        archive = MagicMock()
        archive.cleanup_expired.return_value = [Path("/private/a.json"), Path("/private/b.json")]
        with patch.object(email_agent_check, "_build_archive_service", return_value=archive):
            _, payload = self.run_main("--cleanup", "--dry-run")

        archive.cleanup_expired.assert_called_once_with(
            retention_days=email_agent_check.EMAIL_ARCHIVE_RETENTION_DAYS,
            dry_run=True,
        )
        self.assertEqual(
            payload,
            {
                "check": "cleanup",
                "deleted_count": 0,
                "dry_run": True,
                "matched_count": 2,
                "ok": True,
            },
        )
        self.assertNotIn("private", json.dumps(payload).lower())

    def test_script_never_reads_stdin(self):
        source = Path("qq-ai-bridge/scripts/email_agent_check.py").read_text(encoding="utf-8")

        self.assertNotIn("input(", source)
        self.assertNotIn("sys.stdin", source)


if __name__ == "__main__":
    unittest.main()
