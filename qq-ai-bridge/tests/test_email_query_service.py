import sys
import unittest
from datetime import date, datetime

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.time_utils import LOCAL_TIMEZONE


class EmailQueryServiceTests(unittest.TestCase):
    def setUp(self):
        self.now = datetime(2026, 7, 22, 10, 30, tzinfo=LOCAL_TIMEZONE)

    def parse(self, text: str):
        from apps.qq_ai_bridge.services.email_query_service import parse_email_command

        return parse_email_command(text, now=self.now, max_range_days=31, limit=100)

    def test_today_range(self):
        command = self.parse("邮件 今天")

        self.assertEqual(command.kind, "query")
        self.assertEqual(command.query.start_date, date(2026, 7, 22))
        self.assertEqual(command.query.end_date, date(2026, 7, 22))

    def test_yesterday_range(self):
        command = self.parse("邮件 昨天")

        self.assertEqual(command.query.start_date, date(2026, 7, 21))
        self.assertEqual(command.query.end_date, date(2026, 7, 21))

    def test_this_week_starts_monday(self):
        command = self.parse("邮件 本周")

        self.assertEqual(command.query.start_date, date(2026, 7, 20))
        self.assertEqual(command.query.end_date, date(2026, 7, 22))

    def test_last_week_is_complete_monday_to_sunday(self):
        command = self.parse("邮件 上周")

        self.assertEqual(command.query.start_date, date(2026, 7, 13))
        self.assertEqual(command.query.end_date, date(2026, 7, 19))

    def test_recent_n_days_is_inclusive(self):
        command = self.parse("邮件 最近 7 天")

        self.assertEqual(command.query.start_date, date(2026, 7, 16))
        self.assertEqual(command.query.end_date, date(2026, 7, 22))
        self.assertEqual(command.query.limit, 100)

    def test_recent_days_rejects_zero_and_over_limit(self):
        self.assertEqual(self.parse("邮件 最近 0 天").kind, "invalid")
        self.assertEqual(self.parse("邮件 最近 32 天").kind, "invalid")

    def test_plain_chat_mentioning_email_does_not_match(self):
        command = self.parse("我今天收到一封邮件，帮我看看")

        self.assertEqual(command.kind, "no_match")

    def test_status_help_and_unknown_subcommand_are_distinct(self):
        self.assertEqual(self.parse("邮件 状态").kind, "status")
        self.assertEqual(self.parse("邮件 帮助").kind, "help")
        self.assertEqual(self.parse("邮件 随便看看").kind, "invalid")


if __name__ == "__main__":
    unittest.main()
