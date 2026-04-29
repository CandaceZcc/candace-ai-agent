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

    @patch("apps.qq_ai_bridge.services.vocat_service.call_kimi_text_async", new_callable=AsyncMock)
    @patch("apps.qq_ai_bridge.services.vocat_service.send_private_msg_async", new_callable=AsyncMock)
    async def test_explicit_qq_forward_uses_command_body_only(self, mock_send_private, mock_kimi):
        mock_send_private.return_value = {"ok": True}

        result = await vocat_service.process_vocat_query({"query": "发 QQ 测试"})

        self.assertEqual(result["source"], "qq_forward")
        self.assertEqual(result["targets"], ["qq", "vocat"])
        mock_send_private.assert_awaited_once()
        self.assertEqual(mock_send_private.await_args.args[1], "[VoCat] 测试")
        mock_kimi.assert_not_awaited()

    @patch("apps.qq_ai_bridge.services.vocat_service.call_kimi_text_async", new_callable=AsyncMock)
    @patch("apps.qq_ai_bridge.services.vocat_service.send_private_msg_async", new_callable=AsyncMock)
    async def test_model_refusal_without_raw_query_does_not_forward_or_call_llm(self, mock_send_private, mock_kimi):
        result = await vocat_service.process_vocat_query({"query": "我无法帮你发送 QQ 消息。"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "vocat_model_refusal")
        self.assertEqual(result["reply"], "本机没有拿到原始语音")
        mock_send_private.assert_not_awaited()
        mock_kimi.assert_not_awaited()

    @patch("apps.qq_ai_bridge.services.vocat_service.call_kimi_text_async", new_callable=AsyncMock)
    @patch("apps.qq_ai_bridge.services.vocat_service.send_private_msg_async", new_callable=AsyncMock)
    async def test_raw_query_takes_priority_over_model_reply_for_routing(self, mock_send_private, mock_kimi):
        mock_send_private.return_value = {"ok": True}

        result = await vocat_service.process_vocat_query(
            {"raw_query": "发 QQ 测试", "query": "我无法帮你发送 QQ 消息。"}
        )

        self.assertEqual(result["source"], "qq_forward")
        self.assertEqual(result["query"], "发 QQ 测试")
        self.assertEqual(result["model_reply"], "我无法帮你发送 QQ 消息。")
        self.assertEqual(mock_send_private.await_args.args[1], "[VoCat] 测试")
        mock_kimi.assert_not_awaited()

    @patch("apps.qq_ai_bridge.services.vocat_service.call_kimi_text_async", new_callable=AsyncMock)
    async def test_repo_docs_query_hits_local_repo_docs(self, mock_kimi):
        mock_kimi.return_value = "项目启动：运行 start-agent.sh。"

        result = await vocat_service.process_vocat_query({"query": "项目怎么启动"})

        self.assertTrue(result["ok"])
        self.assertEqual(result["source"], "local_repo_docs")
        self.assertIn("项目启动", result["reply"])
        mock_kimi.assert_awaited_once()

    def test_default_md_root_is_bridge_root_and_finds_project_markdown(self):
        status = vocat_service.get_local_repo_docs_status()

        self.assertTrue(status["md_root"].endswith("qq-ai-bridge"))
        self.assertGreaterEqual(status["md_file_count"], 1)

    def test_repo_markdown_search_excludes_runtime_dirs(self):
        files = vocat_service._iter_repo_markdown_files()
        rendered = [str(path.relative_to(vocat_service.VOCAT_MD_ROOT.expanduser().resolve())) for path in files]

        self.assertTrue(any(item.endswith(".md") for item in rendered))
        self.assertFalse(any(".runtime" in item or "node_modules" in item or "venv" in item for item in rendered))


if __name__ == "__main__":
    unittest.main()
