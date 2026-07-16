import sys
import threading
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.runtime_resources import BoundedExecutor, DelayedTaskScheduler


class RuntimeResourcesTests(unittest.TestCase):
    def test_delayed_scheduler_uses_one_bounded_queue_for_timer_work(self):
        scheduler = DelayedTaskScheduler(name="test-scheduler", max_pending=1)
        event = threading.Event()

        self.assertTrue(scheduler.schedule(1.0, event.set))
        self.assertFalse(scheduler.schedule(1.0, event.set))
        status = scheduler.status()
        self.assertEqual(status["pending"], 1)
        self.assertEqual(status["scheduled"], 1)
        self.assertEqual(status["rejected"], 1)
        scheduler.shutdown(wait=True, cancel_pending=True)

    def test_delayed_scheduler_executes_due_task(self):
        scheduler = DelayedTaskScheduler(name="test-scheduler", max_pending=2)
        event = threading.Event()

        self.assertTrue(scheduler.schedule(0.01, event.set))
        self.assertTrue(event.wait(timeout=1))
        self.assertEqual(scheduler.status()["executed"], 1)
        scheduler.shutdown(wait=True, cancel_pending=True)

    def test_bounded_executor_rejects_when_running_and_pending_slots_are_full(self):
        executor = BoundedExecutor(
            name="test",
            max_workers=1,
            max_pending=1,
        )
        started = threading.Event()
        release = threading.Event()

        def blocking_job():
            started.set()
            release.wait(timeout=2)

        first = executor.try_submit(blocking_job)
        self.assertTrue(started.wait(timeout=1))
        second = executor.try_submit(lambda: None)
        rejected = executor.try_submit(lambda: None)

        self.assertIsNotNone(first)
        self.assertIsNotNone(second)
        self.assertIsNone(rejected)
        status = executor.status()
        self.assertEqual(status["name"], "test")
        self.assertEqual(status["max_workers"], 1)
        self.assertEqual(status["max_pending"], 1)
        self.assertEqual(status["capacity"], 2)
        self.assertEqual(status["active"], 1)
        self.assertEqual(status["pending"], 1)
        self.assertEqual(status["submitted"], 2)
        self.assertEqual(status["rejected"], 1)

        release.set()
        first.result(timeout=1)
        second.result(timeout=1)
        executor.shutdown(wait=True)

    def test_bounded_executor_releases_capacity_after_failure(self):
        executor = BoundedExecutor(name="test", max_workers=1, max_pending=0)

        def failing_job():
            raise RuntimeError("boom")

        future = executor.try_submit(failing_job)
        with self.assertRaises(RuntimeError):
            future.result(timeout=1)

        replacement = executor.try_submit(lambda: "ok")
        self.assertEqual(replacement.result(timeout=1), "ok")
        status = executor.status()
        self.assertEqual(status["active"], 0)
        self.assertEqual(status["pending"], 0)
        self.assertEqual(status["completed"], 2)
        self.assertEqual(status["failed"], 1)
        executor.shutdown(wait=True)


if __name__ == "__main__":
    unittest.main()
