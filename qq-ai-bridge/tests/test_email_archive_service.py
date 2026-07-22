import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.email_models import (
    EmailAttachment,
    EmailDigest,
    EmailEnvelope,
    EmailQuery,
)


class EmailArchiveServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name) / "email"
        self.now = datetime(2026, 7, 22, 12, 0, tzinfo=timezone.utc)
        self.envelope = EmailEnvelope(
            message_id="<private/message:id@example.invalid>",
            subject="Synthetic subject",
            sender="sender@example.invalid",
            recipients=("student@example.invalid",),
            sent_at=datetime(2026, 7, 21, 9, 30, tzinfo=timezone.utc),
            body_text="Synthetic normalized body",
            attachments=(EmailAttachment("notes.txt", "text/plain", 12),),
        )
        self.query = EmailQuery(date(2026, 7, 20), date(2026, 7, 22), limit=100)
        self.digest = EmailDigest(
            period_label="最近 3 天",
            message_count=1,
            summary_text="Synthetic digest",
            source_message_ids=(self.envelope.message_id,),
            from_cache=False,
        )

    def tearDown(self):
        self.temp_dir.cleanup()

    def service(self):
        from apps.qq_ai_bridge.services.email_archive_service import EmailArchiveService

        return EmailArchiveService(self.root, now=lambda: self.now)

    def test_archive_filename_is_hash_not_raw_message_id(self):
        path = self.service().archive_envelope(self.envelope)

        self.assertEqual(path.parent.name, "2026-07-21")
        self.assertRegex(path.name, r"^[0-9a-f]{64}\.json$")
        self.assertNotIn("private", path.name)
        self.assertNotIn("example", path.name)

    def test_archive_json_contains_no_credential_fields(self):
        path = self.service().archive_envelope(self.envelope)

        payload = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(payload["message"]["body_text"], "Synthetic normalized body")
        serialized = json.dumps(payload).lower()
        self.assertNotIn('"username"', serialized)
        self.assertNotIn('"password"', serialized)
        self.assertNotIn('"authorization"', serialized)
        self.assertNotIn('"raw_mime"', serialized)

    def test_write_is_atomic(self):
        from apps.qq_ai_bridge.services import email_archive_service as archive_module

        with (
            patch.object(archive_module.os, "replace", wraps=os.replace) as replace,
            patch.object(archive_module.os, "fsync", wraps=os.fsync) as fsync,
        ):
            path = self.service().archive_envelope(self.envelope)

        replace.assert_called_once()
        fsync.assert_called_once()
        self.assertTrue(path.exists())
        self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_same_message_write_is_idempotent(self):
        from apps.qq_ai_bridge.services import email_archive_service as archive_module

        with patch.object(archive_module.os, "replace", wraps=os.replace) as replace:
            first = self.service().archive_envelope(self.envelope)
            second = self.service().archive_envelope(self.envelope)

        self.assertEqual(first, second)
        self.assertEqual(replace.call_count, 1)

    def test_load_envelope_reconstructs_archived_message_by_hash(self):
        service = self.service()
        path = service.archive_envelope(self.envelope)

        loaded = service.load_envelope(path.stem)

        self.assertEqual(loaded, self.envelope)

    def test_digest_cache_key_includes_range_and_model(self):
        service = self.service()

        first = service.digest_cache_path(self.query, "gpt-5.6-terra")
        different_model = service.digest_cache_path(self.query, "deepseek-v4")
        different_range = service.digest_cache_path(
            EmailQuery(date(2026, 7, 21), date(2026, 7, 22), limit=100),
            "gpt-5.6-terra",
        )

        self.assertEqual(first, service.digest_cache_path(self.query, "gpt-5.6-terra"))
        self.assertNotEqual(first, different_model)
        self.assertNotEqual(first, different_range)
        self.assertTrue(first.name.startswith("2026-07-20_2026-07-22_"))

    def test_daily_and_weekly_digest_paths_are_deterministic(self):
        service = self.service()

        self.assertEqual(
            service.daily_digest_path(date(2026, 7, 22)).relative_to(self.root).as_posix(),
            "digests/daily/2026-07-22.json",
        )
        self.assertEqual(
            service.weekly_digest_path(date(2026, 7, 22)).relative_to(self.root).as_posix(),
            "digests/weekly/2026-W30.json",
        )

    def test_refresh_bypasses_digest_cache(self):
        service = self.service()
        service.write_digest(self.query, "gpt-5.6-terra", self.digest)
        refresh_query = EmailQuery(
            self.query.start_date,
            self.query.end_date,
            self.query.limit,
            refresh=True,
        )

        self.assertIsNone(service.load_digest(refresh_query, "gpt-5.6-terra"))
        cached = service.load_digest(self.query, "gpt-5.6-terra")
        self.assertIsNotNone(cached)
        self.assertTrue(cached.from_cache)

    def test_corrupt_cache_is_quarantined_and_rebuilt(self):
        service = self.service()
        cache_path = service.digest_cache_path(self.query, "gpt-5.6-terra")
        cache_path.parent.mkdir(parents=True)
        cache_path.write_text("{broken-json", encoding="utf-8")

        self.assertIsNone(service.load_digest(self.query, "gpt-5.6-terra"))
        self.assertFalse(cache_path.exists())
        quarantined = list((self.root / "quarantine").iterdir())
        self.assertEqual(len(quarantined), 1)
        self.assertTrue(quarantined[0].name.endswith(cache_path.name))

        service.write_digest(self.query, "gpt-5.6-terra", self.digest)
        rebuilt = service.load_digest(self.query, "gpt-5.6-terra")
        self.assertEqual(rebuilt.summary_text, "Synthetic digest")
        self.assertTrue(rebuilt.from_cache)

    def test_retention_deletes_only_expired_email_archive_files(self):
        service = self.service()
        old_archive = service.archive_envelope(self.envelope)
        fresh_envelope = EmailEnvelope(
            **{**self.envelope.__dict__, "message_id": "<fresh@example.invalid>"}
        )
        fresh_archive = service.archive_envelope(fresh_envelope)
        digest_path = service.write_digest(self.query, "gpt-5.6-terra", self.digest)
        unrelated = self.root / "archive" / "README.txt"
        unrelated.write_text("keep", encoding="utf-8")
        old_timestamp = (self.now - timedelta(days=31)).timestamp()
        os.utime(old_archive, (old_timestamp, old_timestamp))
        os.utime(digest_path, (old_timestamp, old_timestamp))
        os.utime(unrelated, (old_timestamp, old_timestamp))

        deleted = service.cleanup_expired(retention_days=30)

        self.assertEqual(deleted, [old_archive])
        self.assertFalse(old_archive.exists())
        self.assertTrue(fresh_archive.exists())
        self.assertTrue(digest_path.exists())
        self.assertTrue(unrelated.exists())

    def test_retention_never_escapes_email_data_root(self):
        service = self.service()
        outside = Path(self.temp_dir.name) / "outside.json"
        outside.write_text("outside", encoding="utf-8")
        archive_dir = self.root / "archive" / "2026-01-01"
        archive_dir.mkdir(parents=True)
        escape_link = archive_dir / "escape.json"
        escape_link.symlink_to(outside)
        old_timestamp = (self.now - timedelta(days=365)).timestamp()
        os.utime(outside, (old_timestamp, old_timestamp))

        deleted = service.cleanup_expired(retention_days=30)

        self.assertEqual(deleted, [])
        self.assertTrue(outside.exists())
        self.assertTrue(escape_link.is_symlink())

    def test_retention_dry_run_reports_without_deleting(self):
        service = self.service()
        archive_path = service.archive_envelope(self.envelope)
        old_timestamp = (self.now - timedelta(days=31)).timestamp()
        os.utime(archive_path, (old_timestamp, old_timestamp))

        reported = service.cleanup_expired(retention_days=30, dry_run=True)

        self.assertEqual(reported, [archive_path])
        self.assertTrue(archive_path.exists())


if __name__ == "__main__":
    unittest.main()
