import os
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services import scheduler
from apps.qq_ai_bridge.services.reminder_store import SchedulerStateStore


class Barrage6657SchedulerTests(unittest.TestCase):
    @patch("apps.qq_ai_bridge.services.scheduler.sync_6657_barrages_safely")
    def test_startup_sync_only_fetches_configured_lightweight_pages(self, mock_sync):
        mock_sync.return_value = {"ok": True, "stats": {}}

        scheduler._run_6657_startup_sync()

        mock_sync.assert_called_once_with(
            max_pages=scheduler.BARRAGE_6657_STARTUP_SYNC_PAGES,
            log=print,
        )

    @patch("apps.qq_ai_bridge.services.scheduler.sync_6657_barrages_safely")
    def test_daily_sync_marks_state_only_after_success(self, mock_sync):
        now = datetime(2026, 7, 21, 4, 30)
        state_store = unittest.mock.Mock()
        mock_sync.return_value = {"ok": True, "stats": {"barrages": 10}}

        with patch.object(scheduler, "STATE_STORE", state_store):
            scheduler._execute_6657_daily_sync(now, "2026-07-21")

        state_store.mark_daily_sent.assert_called_once_with(
            "barrage_6657_sync",
            "2026-07-21",
            now,
        )

    @patch("apps.qq_ai_bridge.services.scheduler.sync_6657_barrages_safely")
    def test_daily_sync_failure_is_left_for_retry(self, mock_sync):
        now = datetime(2026, 7, 21, 4, 30)
        state_store = unittest.mock.Mock()
        mock_sync.return_value = {"ok": False, "error": "network"}

        with patch.object(scheduler, "STATE_STORE", state_store):
            scheduler._execute_6657_daily_sync(now, "2026-07-21")

        state_store.mark_daily_sent.assert_not_called()

    def test_scheduler_state_persists_6657_daily_token(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            store = SchedulerStateStore(os.path.join(tmpdir, "scheduler.json"))
            now = datetime(2026, 7, 21, 4, 30)

            store.mark_daily_sent("barrage_6657_sync", "2026-07-21", now)

            self.assertTrue(store.was_daily_sent("barrage_6657_sync", "2026-07-21"))


if __name__ == "__main__":
    unittest.main()
