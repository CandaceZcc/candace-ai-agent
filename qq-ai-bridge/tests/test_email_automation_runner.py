import asyncio
import sys
import unittest
from datetime import datetime
from unittest.mock import MagicMock

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.time_utils import LOCAL_TIMEZONE

NOW = datetime(2026, 7, 21, 20, 35, tzinfo=LOCAL_TIMEZONE)


class FakeService:
    def __init__(self, *, poll_error: Exception | None = None):
        self.poll_error = poll_error
        self.poll_calls = []
        self.digest_calls = []

    async def poll(self, now):
        self.poll_calls.append(now)
        if self.poll_error:
            raise self.poll_error

    async def run_digest(self, now, slot):
        self.digest_calls.append((now, slot))


class EmailAutomationRunnerTests(unittest.TestCase):
    def runner(self, service, **overrides):
        from apps.qq_ai_bridge.services.email_automation_runner import EmailAutomationRunner

        values = {
            "service_factory": lambda: service,
            "monitor_enabled": True,
            "digest_enabled": True,
            "poll_interval_seconds": 300,
            "digest_times": ("12:30", "20:30"),
            "now": lambda: NOW,
            "sleep": MagicMock(),
            "run_async": asyncio.run,
        }
        values.update(overrides)
        return EmailAutomationRunner(**values)

    def test_run_once_polls_and_runs_due_slots_from_last_24_hours(self):
        service = FakeService()
        runner = self.runner(service)

        runner.run_once(service, NOW)

        self.assertEqual(service.poll_calls, [NOW])
        scheduled = [slot for _, slot in service.digest_calls]
        self.assertEqual(
            scheduled,
            [
                datetime(2026, 7, 21, 12, 30, tzinfo=LOCAL_TIMEZONE),
                datetime(2026, 7, 21, 20, 30, tzinfo=LOCAL_TIMEZONE),
            ],
        )

    def test_restart_catches_up_yesterday_slot_only_within_24_hours(self):
        service = FakeService()
        now = datetime(2026, 7, 21, 10, 0, tzinfo=LOCAL_TIMEZONE)

        self.runner(service).run_once(service, now)

        self.assertEqual(
            [slot for _, slot in service.digest_calls],
            [
                datetime(2026, 7, 20, 12, 30, tzinfo=LOCAL_TIMEZONE),
                datetime(2026, 7, 20, 20, 30, tzinfo=LOCAL_TIMEZONE),
            ],
        )

    def test_monitor_and_digest_flags_are_independent(self):
        digest_only = FakeService()
        self.runner(digest_only, monitor_enabled=False).run_once(digest_only, NOW)
        self.assertEqual(digest_only.poll_calls, [])
        self.assertTrue(digest_only.digest_calls)

        monitor_only = FakeService()
        self.runner(monitor_only, digest_enabled=False).run_once(monitor_only, NOW)
        self.assertEqual(monitor_only.poll_calls, [NOW])
        self.assertEqual(monitor_only.digest_calls, [])

    def test_poll_exception_does_not_block_due_digest(self):
        service = FakeService(poll_error=RuntimeError("synthetic"))

        self.runner(service).run_once(service, NOW)

        self.assertTrue(service.digest_calls)

    def test_run_forever_polls_immediately_then_sleeps_configured_interval(self):
        service = FakeService()
        sleep = MagicMock(side_effect=KeyboardInterrupt)
        runner = self.runner(service, sleep=sleep)

        with self.assertRaises(KeyboardInterrupt):
            runner.run_forever()

        self.assertEqual(service.poll_calls, [NOW])
        sleep.assert_called_once_with(300)

    def test_run_forever_retries_after_service_factory_failure(self):
        service = FakeService()
        service_factory = MagicMock(side_effect=(RuntimeError("invalid state"), service))
        sleep = MagicMock(side_effect=(None, KeyboardInterrupt))
        runner = self.runner(
            service,
            service_factory=service_factory,
            sleep=sleep,
        )

        with self.assertRaises(KeyboardInterrupt):
            runner.run_forever()

        self.assertEqual(service.poll_calls, [NOW])
        self.assertEqual(service_factory.call_count, 2)
        self.assertEqual(sleep.call_args_list[0].args, (300,))

    def test_disabled_start_does_not_create_thread(self):
        from apps.qq_ai_bridge.services.email_automation_runner import start_email_automation

        thread_factory = MagicMock()

        result = start_email_automation(
            monitor_enabled=False,
            digest_enabled=False,
            thread_factory=thread_factory,
        )

        self.assertIsNone(result)
        thread_factory.assert_not_called()


if __name__ == "__main__":
    unittest.main()
