import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services import private_ledger_service
from apps.qq_ai_bridge.services.private_ledger_service import (
    _PRIVATE_LEDGER_ARTIFACTS,
    maybe_handle_private_ledger_command,
    parse_ledger_text,
)


class PrivateLedgerServiceTests(unittest.TestCase):
    def setUp(self):
        _PRIVATE_LEDGER_ARTIFACTS.clear()

    def test_parse_ledger_sums_plus_expression(self):
        artifact = parse_ledger_text(
            273007866,
            "记账4.20-4.30\nKimi API充值: 50\n论文查重：25+30+35+12",
        )

        self.assertIsNotNone(artifact)
        self.assertEqual(str(artifact.total), "152")
        self.assertEqual(artifact.items[1].name, "论文查重")
        self.assertEqual(str(artifact.items[1].amount), "102")
        self.assertIn("4.20-4.30 额外开销，共 152 元", artifact.pages[0])

    def test_parse_ledger_keeps_date_like_item_names(self):
        artifact = parse_ledger_text(273007866, "记账4.20-4.30\n4.26火锅: 122\n4.24外食: 80")

        self.assertIsNotNone(artifact)
        self.assertEqual(artifact.items[0].name, "4.26火锅")
        self.assertEqual(artifact.items[1].name, "4.24外食")

    def test_parse_ledger_handles_single_line_qq_text(self):
        artifact = parse_ledger_text(
            273007866,
            "记账4.20-4.30（订5.1假期票之后，除必备之外的额外开销） "
            "充值kimi api: 50 论文查重：25+30+35+12 治疗手：160 腱鞘贴：20 "
            "Codex额度：120+66+67+10 SD卡：23+30 即食牛肉：112 短袖：60 "
            "ChatGPT订阅：170 4.26火锅：122 4.24外食：80 喝酒：98",
        )

        self.assertIsNotNone(artifact)
        self.assertEqual(str(artifact.total), "1290")
        self.assertEqual(len(artifact.items), 12)
        self.assertEqual(artifact.items[0].name, "充值kimi api")
        self.assertEqual(artifact.items[9].name, "4.26火锅")

    def test_owner_ledger_request_stores_artifact_and_first_page(self):
        result = maybe_handle_private_ledger_command(
            273007866,
            "记账4.20-4.30\nKimi API充值: 50\n论文查重：25+30+35+12",
        )

        self.assertTrue(result["handled"])
        self.assertEqual(result["mode"], "parsed")
        self.assertIn("共 152 元", result["reply"])
        self.assertIn("273007866", _PRIVATE_LEDGER_ARTIFACTS)

    def test_continue_uses_last_artifact_without_llm(self):
        old_limit = private_ledger_service.LEDGER_PAGE_CHAR_LIMIT
        private_ledger_service.LEDGER_PAGE_CHAR_LIMIT = 60
        try:
            maybe_handle_private_ledger_command(
                273007866,
                "记账4.20-4.30\n"
                "项目一: 10\n项目二: 20\n项目三: 30\n项目四: 40\n项目五: 50\n项目六: 60",
            )
            result = maybe_handle_private_ledger_command(273007866, "继续")
        finally:
            private_ledger_service.LEDGER_PAGE_CHAR_LIMIT = old_limit

        self.assertTrue(result["handled"])
        self.assertIn(result["mode"], {"continued", "done"})
        self.assertNotIn("继续什么", result["reply"])

    def test_full_ledger_returns_multiple_pages_when_available(self):
        old_limit = private_ledger_service.LEDGER_PAGE_CHAR_LIMIT
        private_ledger_service.LEDGER_PAGE_CHAR_LIMIT = 60
        try:
            maybe_handle_private_ledger_command(
                273007866,
                "记账4.20-4.30\n"
                "项目一: 10\n项目二: 20\n项目三: 30\n项目四: 40\n项目五: 50\n项目六: 60",
            )
            result = maybe_handle_private_ledger_command(273007866, "输出完整账单")
        finally:
            private_ledger_service.LEDGER_PAGE_CHAR_LIMIT = old_limit

        self.assertTrue(result["handled"])
        self.assertEqual(result["mode"], "full")
        self.assertGreaterEqual(result["force_parts"], 1)
        self.assertIn("项目", result["reply"])

    def test_reoutput_without_artifact_does_not_fall_through_to_llm(self):
        result = maybe_handle_private_ledger_command(273007866, "重新输出")

        self.assertTrue(result["handled"])
        self.assertEqual(result["mode"], "missing")
        self.assertIn("没有可继续的账单", result["reply"])

    def test_non_owner_does_not_handle_ledger(self):
        result = maybe_handle_private_ledger_command(123, "记账\nKimi: 50")

        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
