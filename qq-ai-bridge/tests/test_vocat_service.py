import sys
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services import vocat_service


class VocatServiceTests(unittest.IsolatedAsyncioTestCase):
    @patch("apps.qq_ai_bridge.services.vocat_service.call_kimi_text_async", new_callable=AsyncMock)
    @patch("apps.qq_ai_bridge.services.vocat_service.send_private_msg_async", new_callable=AsyncMock)
    async def test_function_call_voice_reply_is_forwarded_to_qq(self, mock_send_private, mock_kimi):
        mock_kimi.return_value = "本机回复"
        mock_send_private.return_value = {"ok": True}

        result = await vocat_service.process_vocat_query(
            {"query": "今天状态如何", "source": "vocat_function_call"}
        )

        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], "本机回复")
        self.assertEqual(result["qq_result"], {"ok": True})
        mock_send_private.assert_awaited_once()
        self.assertIn("今天状态如何", mock_send_private.await_args.args[1])
        self.assertIn("本机回复", mock_send_private.await_args.args[1])

    @patch("apps.qq_ai_bridge.services.vocat_service.call_kimi_text_async", new_callable=AsyncMock)
    @patch("apps.qq_ai_bridge.services.vocat_service.send_private_msg_async", new_callable=AsyncMock)
    async def test_plain_webhook_query_does_not_forward_by_default(self, mock_send_private, mock_kimi):
        mock_kimi.return_value = "普通回复"

        result = await vocat_service.process_vocat_query({"query": "普通请求"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["reply"], "普通回复")
        self.assertNotIn("qq_result", result)
        mock_send_private.assert_not_awaited()

    @patch("apps.qq_ai_bridge.services.vocat_service.call_kimi_text_async", new_callable=AsyncMock)
    async def test_expression_smoke_query_is_handled_locally(self, mock_kimi):
        result = await vocat_service.process_vocat_query({"query": "测试表情"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_expression_test")
        self.assertEqual(result["expression"], "happy")
        mock_kimi.assert_not_awaited()

    @patch("apps.qq_ai_bridge.services.vocat_service.call_kimi_text_async", new_callable=AsyncMock)
    async def test_expression_command_without_expression_word_is_handled_locally(self, mock_kimi):
        result = await vocat_service.process_vocat_query({"query": "切换生气"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_expression")
        self.assertEqual(result["expression"], "angry")
        mock_kimi.assert_not_awaited()

    @patch("apps.qq_ai_bridge.services.vocat_service.call_kimi_text_async", new_callable=AsyncMock)
    async def test_spoken_tts_sentence_does_not_trigger_expression_smoke(self, mock_kimi):
        mock_kimi.return_value = "普通播报回复"

        result = await vocat_service.process_vocat_query({"query": "现在测试表情切换"})

        self.assertTrue(result["ok"])
        self.assertNotEqual(result["source"], "local_expression_test")

    @patch("apps.qq_ai_bridge.services.vocat_service.call_kimi_text_async", new_callable=AsyncMock)
    async def test_plain_expression_word_does_not_force_angry_from_reply(self, mock_kimi):
        mock_kimi.return_value = "这里有一些表情符号：开心、生气、睡觉。"

        result = await vocat_service.process_vocat_query({"query": "介绍一些表情符号"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "kimi")
        self.assertEqual(result["expression"], "happy")


if __name__ == "__main__":
    unittest.main()
