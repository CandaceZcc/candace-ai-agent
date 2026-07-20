import sys
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.skills.chat import ChatSkill
from shared.ai.agent_runtime import AgentRunResult


def _prompt_payload(prompt: str = "legacy prompt") -> dict:
    return {
        "prompt": prompt,
        "prompt_mode": "test",
        "query_len": 2,
        "history_chars": 0,
        "history_items": 0,
        "instruction_chars": 0,
        "prompt_chars": len(prompt),
    }


class PrivateAgentIntegrationTests(unittest.TestCase):
    def test_disabled_flag_uses_legacy_path(self):
        from apps.qq_ai_bridge.services import private_chat_service

        with (
            patch("apps.qq_ai_bridge.services.private_chat_service.AGENT_RUNTIME_ENABLED", False),
            patch("apps.qq_ai_bridge.services.private_chat_service.call_ai", return_value="legacy") as mock_call,
            patch("apps.qq_ai_bridge.services.private_chat_service.AgentRuntime") as mock_runtime,
        ):
            reply = private_chat_service._generate_private_model_reply(
                273007866,
                "你好",
                _prompt_payload(),
                merged_count=1,
                trace_id="trace-1",
            )

        self.assertEqual(reply, "legacy")
        mock_call.assert_called_once()
        mock_runtime.assert_not_called()

    def test_enabled_owner_private_message_uses_agent_runtime(self):
        from apps.qq_ai_bridge.services import private_chat_service

        runtime = MagicMock()
        runtime.run = AsyncMock(
            return_value=AgentRunResult(
                ok=True,
                output_text="agent reply",
                provider="responses_proxy",
                model="gpt-5.6",
                tool_names=(),
            )
        )
        with (
            patch("apps.qq_ai_bridge.services.private_chat_service.AGENT_RUNTIME_ENABLED", True),
            patch("apps.qq_ai_bridge.services.private_chat_service.OWNER_QQ", 273007866),
            patch("apps.qq_ai_bridge.services.private_chat_service.AgentRuntime", return_value=runtime),
            patch("apps.qq_ai_bridge.services.private_chat_service.call_ai") as mock_call,
        ):
            reply = private_chat_service._generate_private_model_reply(
                273007866,
                "你好",
                _prompt_payload(),
                merged_count=1,
                trace_id="trace-1",
            )

        self.assertEqual(reply, "agent reply")
        mock_call.assert_not_called()
        request = runtime.run.call_args.args[0]
        self.assertEqual(request.route, "private_chat")
        self.assertEqual(request.allowed_tool_names, ())

    def test_group_service_is_unchanged(self):
        context = SkillContext(
            data={"message_id": 123},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=2,
            group_id=3,
            group_config={"reply_all_messages": True, "bot_can_reply": True},
            should_log=True,
            msg="宝宝你好",
            normalized_msg="宝宝你好",
            effective_text="宝宝你好",
            mentioned_self=True,
            image_inputs={},
            file_info=None,
            logger=lambda *_args: None,
            timestamp=10,
            nick="u",
        )

        with (
            patch("apps.qq_ai_bridge.skills.chat.enqueue_group_text", return_value={"queued": True}) as mock_enqueue,
            patch("apps.qq_ai_bridge.services.private_chat_service.AgentRuntime") as mock_runtime,
        ):
            result = ChatSkill().handle(context)

        self.assertTrue(result.handled)
        mock_enqueue.assert_called_once()
        mock_runtime.assert_not_called()

    def test_compact_context_is_bounded_before_sdk_run(self):
        from apps.qq_ai_bridge.services import private_chat_service

        runtime = MagicMock()
        runtime.run = AsyncMock(
            return_value=AgentRunResult(
                ok=True,
                output_text="ok",
                provider="responses_proxy",
                model="gpt-5.6",
                tool_names=(),
            )
        )
        with (
            patch("apps.qq_ai_bridge.services.private_chat_service.AGENT_RUNTIME_ENABLED", True),
            patch("apps.qq_ai_bridge.services.private_chat_service.OWNER_QQ", 273007866),
            patch("apps.qq_ai_bridge.services.private_chat_service.AgentRuntime", return_value=runtime),
        ):
            private_chat_service._generate_private_model_reply(
                273007866,
                "你好",
                _prompt_payload("x" * 10000),
                merged_count=1,
                trace_id=None,
            )

        request = runtime.run.call_args.args[0]
        self.assertLessEqual(len(request.compact_context), 4000)

    def test_capability_error_is_sent_without_legacy_retry(self):
        from apps.qq_ai_bridge.services import private_chat_service

        runtime = MagicMock()
        runtime.run = AsyncMock(
            return_value=AgentRunResult(
                ok=False,
                output_text="工具不可用，稍后再试。",
                provider="responses_proxy",
                model="gpt-5.6",
                tool_names=("web_search",),
                failure_code="tool_error",
            )
        )
        with (
            patch("apps.qq_ai_bridge.services.private_chat_service.AGENT_RUNTIME_ENABLED", True),
            patch("apps.qq_ai_bridge.services.private_chat_service.OWNER_QQ", 273007866),
            patch("apps.qq_ai_bridge.services.private_chat_service.AgentRuntime", return_value=runtime),
            patch("apps.qq_ai_bridge.services.private_chat_service.call_ai") as mock_call,
        ):
            reply = private_chat_service._generate_private_model_reply(
                273007866,
                "查一下今天新闻",
                _prompt_payload(),
                merged_count=1,
                trace_id=None,
            )

        self.assertEqual(reply, "工具不可用，稍后再试。")
        mock_call.assert_not_called()

    def test_safe_provider_failure_uses_legacy_once_when_enabled(self):
        from apps.qq_ai_bridge.services import private_chat_service

        runtime = MagicMock()
        runtime.run = AsyncMock(
            return_value=AgentRunResult(
                ok=True,
                output_text="legacy reply",
                provider="responses_proxy",
                model="gpt-5.6",
                tool_names=(),
                used_legacy_fallback=True,
            )
        )
        with (
            patch("apps.qq_ai_bridge.services.private_chat_service.AGENT_RUNTIME_ENABLED", True),
            patch("apps.qq_ai_bridge.services.private_chat_service.OWNER_QQ", 273007866),
            patch("apps.qq_ai_bridge.services.private_chat_service.AgentRuntime", return_value=runtime) as ctor,
        ):
            reply = private_chat_service._generate_private_model_reply(
                273007866,
                "你好",
                _prompt_payload(),
                merged_count=1,
                trace_id=None,
            )

        self.assertEqual(reply, "legacy reply")
        self.assertIs(ctor.call_args.kwargs["legacy_call"], private_chat_service.call_ai)

    def test_non_idempotent_tool_failure_never_falls_back(self):
        from apps.qq_ai_bridge.services import private_chat_service

        runtime = MagicMock()
        runtime.run = AsyncMock(
            return_value=AgentRunResult(
                ok=False,
                output_text="电脑动作需要确认。",
                provider="responses_proxy",
                model="gpt-5.6",
                tool_names=("pc_open_http_url",),
                failure_code="tool_error",
            )
        )
        with (
            patch("apps.qq_ai_bridge.services.private_chat_service.AGENT_RUNTIME_ENABLED", True),
            patch("apps.qq_ai_bridge.services.private_chat_service.OWNER_QQ", 273007866),
            patch("apps.qq_ai_bridge.services.private_chat_service.AgentRuntime", return_value=runtime),
            patch("apps.qq_ai_bridge.services.private_chat_service.call_ai") as mock_call,
        ):
            reply = private_chat_service._generate_private_model_reply(
                273007866,
                "browser 打开 https://example.com",
                _prompt_payload(),
                merged_count=1,
                trace_id=None,
            )

        self.assertEqual(reply, "电脑动作需要确认。")
        mock_call.assert_not_called()


if __name__ == "__main__":
    unittest.main()
