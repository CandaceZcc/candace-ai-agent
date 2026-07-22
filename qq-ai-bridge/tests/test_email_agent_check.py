import asyncio
import io
import json
import sys
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.time_utils import LOCAL_TIMEZONE


class FakeSimulationClassifier:
    async def classify(self, candidates):
        from apps.qq_ai_bridge.services.email_models import EmailClassification

        results = []
        for alias, envelope, _decision in candidates:
            if "CST3001" in envelope.subject:
                results.append(
                    EmailClassification(
                        alias=alias,
                        relevance_score=97,
                        urgency="critical",
                        category="exam_change",
                        concise_title="CST3001 考试时间调整",
                        summary="考试时间已经调整。",
                        action="请在今天确认新安排。",
                        deadline=None,
                        reason="与你的大三课程和考试直接相关",
                        confidence=0.99,
                    )
                )
            else:
                results.append(
                    EmailClassification(
                        alias=alias,
                        relevance_score=86,
                        urgency="medium",
                        category="robotics_competition",
                        concise_title="机器人与嵌入式竞赛通知",
                        summary="学院发布了机器人竞赛信息。",
                        action="",
                        deadline=None,
                        reason="与你关注的机器人和嵌入式方向相关",
                        confidence=0.96,
                    )
                )
        return tuple(results)


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

    def test_simulation_requires_explicit_qq_acceptance(self):
        from scripts import email_agent_check

        with self.assertRaises(SystemExit):
            email_agent_check.main(["--simulate-automation", "--deliver-to-owner"])

    def test_simulation_delivery_flags_require_simulation_mode(self):
        from scripts import email_agent_check

        with self.assertRaises(SystemExit):
            email_agent_check.main(["--config", "--deliver-to-owner", "--accept-qq-send"])

    def test_cursor_bootstrap_requires_explicit_skip_acceptance(self):
        from scripts import email_agent_check

        with self.assertRaises(SystemExit):
            email_agent_check.main(["--bootstrap-cursor"])

    def test_cursor_bootstrap_uses_latest_readonly_snapshot_without_exposing_uid(self):
        from scripts import email_agent_check

        imap = MagicMock()
        imap.snapshot_cursor.return_value = SimpleNamespace(uid_validity="44", latest_uid=900)
        store = MagicMock()
        store.cursor.return_value = SimpleNamespace(uid_validity="44", last_uid=850)
        with (
            patch.object(email_agent_check, "_build_imap_service", return_value=imap),
            patch.object(email_agent_check, "_build_processing_store", return_value=store),
        ):
            payload = email_agent_check._bootstrap_automation_cursor()

        store.set_cursor.assert_called_once_with("INBOX", "44", 900)
        self.assertEqual(
            payload,
            {
                "check": "cursor_bootstrap",
                "cursor_initialized": True,
                "mailbox_had_existing_cursor": True,
                "ok": True,
            },
        )
        self.assertNotIn("900", json.dumps(payload))

    def test_cursor_bootstrap_never_moves_same_mailbox_cursor_backwards(self):
        from scripts import email_agent_check

        imap = MagicMock()
        imap.snapshot_cursor.return_value = SimpleNamespace(uid_validity="44", latest_uid=800)
        store = MagicMock()
        store.cursor.return_value = SimpleNamespace(uid_validity="44", last_uid=850)
        with (
            patch.object(email_agent_check, "_build_imap_service", return_value=imap),
            patch.object(email_agent_check, "_build_processing_store", return_value=store),
        ):
            email_agent_check._bootstrap_automation_cursor()

        store.set_cursor.assert_called_once_with("INBOX", "44", 850)

    def test_cursor_bootstrap_cli_reports_safe_operation_error(self):
        from scripts import email_agent_check

        with patch.object(
            email_agent_check,
            "_bootstrap_automation_cursor",
            side_effect=RuntimeError("private state path"),
        ):
            exit_code, payload = self.run_main(
                "--bootstrap-cursor",
                "--accept-skip-existing",
            )

        self.assertEqual(exit_code, 1)
        self.assertEqual(
            payload,
            {"check": "cursor_bootstrap", "error": "RuntimeError", "ok": False},
        )
        self.assertNotIn("private state path", json.dumps(payload))

    def test_simulation_routes_scenarios_without_live_send(self):
        from scripts import email_agent_check

        live_sender = MagicMock(return_value={"ok": True})

        with patch.object(email_agent_check, "EMAIL_MAX_MESSAGES_PER_RUN", 1):
            payload = asyncio.run(
                email_agent_check._run_automation_simulation(
                    deliver_to_owner=False,
                    semantic_classifier=FakeSimulationClassifier(),
                    send_private=live_sender,
                )
            )

        self.assertTrue(payload["ok"])
        self.assertFalse(payload["delivered_to_owner"])
        self.assertEqual(
            [item["route"] for item in payload["scenarios"]],
            ["immediate", "digest", "ignore"],
        )
        self.assertEqual(
            payload["send_counts"],
            {"digest": 1, "immediate": 1, "total": 2},
        )
        self.assertEqual(payload["idempotency"], {"digest": True, "poll": True})
        live_sender.assert_not_called()
        serialized = json.dumps(payload, ensure_ascii=False)
        for forbidden in (
            "owner@example.invalid",
            "course-instructor@example.invalid",
            "CST3001 Final Examination",
            "campus recruitment",
        ):
            self.assertNotIn(forbidden, serialized)

    def test_live_simulation_labels_and_redacts_exactly_two_qq_sends(self):
        from scripts import email_agent_check

        sends = []

        def sender(user_id, text, **kwargs):
            sends.append((user_id, text, kwargs))
            return {"ok": True}

        payload = asyncio.run(
            email_agent_check._run_automation_simulation(
                deliver_to_owner=True,
                semantic_classifier=FakeSimulationClassifier(),
                send_private=sender,
            )
        )

        self.assertTrue(payload["ok"])
        self.assertTrue(payload["delivered_to_owner"])
        self.assertEqual(len(sends), 2)
        for _, text, kwargs in sends:
            self.assertTrue(text.startswith("【邮件自动推送模拟】"))
            self.assertTrue(kwargs["redact_content"])
            self.assertTrue(kwargs["quiet"])

    def test_simulation_cli_returns_safe_json(self):
        from scripts import email_agent_check

        report = {
            "check": "automation_simulation",
            "delivered_to_owner": False,
            "idempotency": {"digest": True, "poll": True},
            "ok": True,
            "scenarios": [],
            "send_counts": {"digest": 0, "immediate": 0, "total": 0},
        }
        with patch.object(
            email_agent_check,
            "_run_automation_simulation",
            new=AsyncMock(return_value=report),
        ) as simulate:
            exit_code, payload = self.run_main("--simulate-automation")

        self.assertEqual(exit_code, 0)
        self.assertEqual(payload, report)
        simulate.assert_awaited_once_with(deliver_to_owner=False)

    def test_script_never_reads_stdin(self):
        source = Path("qq-ai-bridge/scripts/email_agent_check.py").read_text(encoding="utf-8")

        self.assertNotIn("input(", source)
        self.assertNotIn("sys.stdin", source)


if __name__ == "__main__":
    unittest.main()
