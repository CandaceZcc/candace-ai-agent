import os
import sys
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.runtime_maintenance import (
    RotatingLogSink,
    TeeStream,
    cleanup_log_backups,
    cleanup_temp_directory,
    get_directory_status,
)


class RuntimeMaintenanceTests(unittest.TestCase):
    def test_cleanup_log_backups_preserves_current_log_and_removes_expired_backup(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            current = root / "bridge.log"
            expired = root / "bridge.log.bak.old"
            recent = root / "bridge.log.1"
            unrelated = root / "agent.log"
            current.write_bytes(b"c" * 10)
            expired.write_bytes(b"e" * 20)
            recent.write_bytes(b"r" * 30)
            unrelated.write_bytes(b"u" * 40)
            os.utime(expired, (800, 800))
            os.utime(recent, (950, 950))

            result = cleanup_log_backups(
                current,
                max_age_seconds=100,
                max_total_bytes=100,
                now=1000,
            )

            self.assertEqual(result["removed_files"], 1)
            self.assertTrue(current.exists())
            self.assertFalse(expired.exists())
            self.assertTrue(recent.exists())
            self.assertTrue(unrelated.exists())

    def test_tee_stream_does_not_flush_partial_print_writes_into_blank_log_lines(self):
        original = StringIO()
        sink = MagicMock()
        stream = TeeStream(original, sink, "stdout")

        stream.write("hello")
        stream.write("\n")

        self.assertEqual(original.getvalue(), "hello\n")
        self.assertEqual(sink.write.call_count, 2)
        sink.flush.assert_not_called()

        stream.flush()
        sink.flush.assert_called_once_with(stream_name="stdout")

    def test_cleanup_temp_directory_removes_stale_then_oldest_until_under_size_cap(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            old = root / "old.jpg"
            large = root / "large.jpg"
            recent = root / "recent.jpg"
            old.write_bytes(b"o" * 20)
            large.write_bytes(b"l" * 60)
            recent.write_bytes(b"r" * 30)
            os.utime(old, (800, 800))
            os.utime(large, (900, 900))
            os.utime(recent, (950, 950))

            result = cleanup_temp_directory(
                root,
                max_age_seconds=100,
                max_total_bytes=50,
                now=1000,
            )

            self.assertEqual(result["removed_files"], 2)
            self.assertEqual(result["removed_bytes"], 80)
            self.assertFalse(old.exists())
            self.assertFalse(large.exists())
            self.assertTrue(recent.exists())
            self.assertEqual(result["total_bytes"], 30)
            self.assertEqual(result["file_count"], 1)

    def test_get_directory_status_reports_file_count_and_total_bytes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "a.bin").write_bytes(b"123")
            (root / "nested").mkdir()
            (root / "nested" / "b.bin").write_bytes(b"4567")

            status = get_directory_status(root)

            self.assertEqual(status["file_count"], 2)
            self.assertEqual(status["total_bytes"], 7)
            self.assertEqual(status["path"], str(root.resolve()))

    def test_rotating_log_sink_rotates_without_a_second_file_writer(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "bridge.log"
            sink = RotatingLogSink(path, max_bytes=80, backup_count=2)
            for index in range(20):
                sink.write(f"line-{index:02d}-abcdefghijk\n", stream_name="stdout")
            sink.close()

            self.assertTrue(path.exists())
            self.assertTrue(Path(f"{path}.1").exists())


if __name__ == "__main__":
    unittest.main()
