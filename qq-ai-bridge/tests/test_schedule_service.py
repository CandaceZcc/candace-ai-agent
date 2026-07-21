import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.schedule_service import detect_schedule_intent


class ScheduleServiceTests(unittest.TestCase):
    def test_today_schedule_phrases_match(self):
        self.assertEqual(detect_schedule_intent("今天有什么课"), "today_schedule")
        self.assertEqual(detect_schedule_intent("帮我看看今天课表"), "today_schedule")
        self.assertEqual(detect_schedule_intent("查询一下今日课程安排"), "today_schedule")

    def test_tomorrow_schedule_phrases_match(self):
        self.assertEqual(detect_schedule_intent("明天有什么课"), "tomorrow_schedule")
        self.assertEqual(detect_schedule_intent("明天课表呢"), "tomorrow_schedule")
        self.assertEqual(detect_schedule_intent("看看明日课程安排"), "tomorrow_schedule")

    def test_plain_course_mentions_do_not_match_schedule(self):
        self.assertIsNone(detect_schedule_intent("我今天有课程设计要交"))
        self.assertIsNone(detect_schedule_intent("帮我写一个课程总结"))
        self.assertIsNone(detect_schedule_intent("这个学期课程好多"))
        self.assertIsNone(detect_schedule_intent("课表我晚点自己看，你先帮我写邮件"))

    def test_tomorrow_overview_still_matches(self):
        self.assertEqual(detect_schedule_intent("明天有什么课和提醒"), "tomorrow_overview")

    def test_mis_triggering_generic_phrases(self):
        # This should match today's schedule exactly
        self.assertEqual(detect_schedule_intent("有什么课"), "today_schedule")
        # These should no longer match
        self.assertIsNone(
            detect_schedule_intent("下周一有什么课"),
            "Should not match today's schedule for future dates",
        )
        self.assertIsNone(
            detect_schedule_intent("这学期有什么课"),
            "Should not match today's schedule for semester queries",
        )

    def test_start_scheduler_starts_email_runner_without_changing_reminder_thread(self):
        from apps.qq_ai_bridge.services import scheduler

        reminder_thread = MagicMock()
        with (
            patch.object(scheduler, "_STARTED", False),
            patch.object(scheduler, "ensure_schedule_file"),
            patch.object(scheduler.threading, "Thread", return_value=reminder_thread) as thread,
            patch.object(scheduler, "start_email_automation") as start_email,
        ):
            scheduler.start_scheduler()

        thread.assert_called_once_with(
            target=scheduler._scheduler_loop,
            name="qq-reminder-scheduler",
            daemon=True,
        )
        reminder_thread.start.assert_called_once_with()
        start_email.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
