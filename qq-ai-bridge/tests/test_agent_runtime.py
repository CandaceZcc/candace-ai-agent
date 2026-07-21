import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

sys.path.insert(0, "qq-ai-bridge")


def _binding():
    from shared.ai.agent_provider import AgentModelBinding, ProviderCapabilities

    return AgentModelBinding(
        provider="responses_proxy",
        model=MagicMock(name="model"),
        model_name="gpt-5.6",
        capabilities=ProviderCapabilities(
            responses=True,
            function_tools=True,
            hosted_web_search=False,
            builtin_computer=False,
            openai_trace_export=False,
            verified=True,
        ),
    )


class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_pc_agent_instructions_delegate_approval_to_tools(self):
        from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime

        with (
            patch("shared.ai.agent_runtime.build_agent_model_binding", return_value=_binding()),
            patch("shared.ai.agent_runtime.Agent") as mock_agent,
            patch("shared.ai.agent_runtime.Runner.run", new_callable=AsyncMock) as mock_run,
        ):
            mock_run.return_value = SimpleNamespace(final_output="Approval required")
            await AgentRuntime(tool_resolver=lambda _names, _capabilities: []).run(
                AgentRunRequest(
                    route="pc_agent",
                    user_text="click Submit payment",
                    compact_context="",
                    allowed_tool_names=("pc_browser_click_text",),
                    trace_id="trace-approval",
                )
            )

        instructions = mock_agent.call_args.kwargs["instructions"]
        self.assertIn("call the matching tool", instructions.lower())
        self.assertIn("needs_approval=true", instructions)
        self.assertIn("ok=true", instructions)

    async def test_reports_sdk_usage_and_tool_call_counts(self):
        from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime

        usage = SimpleNamespace(
            input_tokens=120,
            output_tokens=30,
            input_tokens_details=SimpleNamespace(cached_tokens=40),
        )
        new_items = [
            SimpleNamespace(raw_item={"type": "web_search_call"}),
            SimpleNamespace(raw_item={"type": "function_call"}),
        ]
        with (
            patch("shared.ai.agent_runtime.build_agent_model_binding", return_value=_binding()),
            patch("shared.ai.agent_runtime.Agent"),
            patch("shared.ai.agent_runtime.Runner.run", new_callable=AsyncMock) as mock_run,
        ):
            mock_run.return_value = SimpleNamespace(
                final_output="OK",
                new_items=new_items,
                raw_responses=[SimpleNamespace(usage=usage)],
            )
            result = await AgentRuntime().run(
                AgentRunRequest(
                    route="current_events",
                    user_text="查一下最新消息",
                    compact_context="",
                    allowed_tool_names=(),
                    trace_id="trace-usage",
                )
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.input_tokens, 120)
        self.assertEqual(result.cached_input_tokens, 40)
        self.assertEqual(result.output_tokens, 30)
        self.assertEqual(result.hosted_search_calls, 1)
        self.assertEqual(result.local_tool_calls, 1)

    async def test_appends_visible_citations_from_sdk_items(self):
        from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime

        citation_item = SimpleNamespace(
            raw_item={
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "Answer",
                        "annotations": [
                            {
                                "type": "url_citation",
                                "title": "QuotaAPI Docs",
                                "url": "https://quotarouter.ai/docs/zh/quickstart",
                            }
                        ],
                    }
                ],
            }
        )
        with (
            patch("shared.ai.agent_runtime.build_agent_model_binding", return_value=_binding()),
            patch("shared.ai.agent_runtime.Agent"),
            patch("shared.ai.agent_runtime.Runner.run", new_callable=AsyncMock) as mock_run,
        ):
            mock_run.return_value = SimpleNamespace(
                final_output="这里是答案。",
                new_items=[citation_item],
            )
            result = await AgentRuntime().run(
                AgentRunRequest(
                    route="current_events",
                    user_text="查一下最新消息",
                    compact_context="",
                    allowed_tool_names=(),
                    trace_id="trace-search",
                )
            )

        self.assertTrue(result.ok)
        self.assertIn("来源：", result.output_text)
        self.assertIn("https://quotarouter.ai/docs/zh/quickstart", result.output_text)

    async def test_applies_reasoning_effort_and_disables_response_storage(self):
        from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime

        with (
            patch("shared.ai.agent_runtime.build_agent_model_binding", return_value=_binding()),
            patch("shared.ai.agent_runtime.Agent") as mock_agent,
            patch("shared.ai.agent_runtime.Runner.run", new_callable=AsyncMock) as mock_run,
            patch("shared.ai.agent_runtime.AGENT_MODEL_REASONING_EFFORT", "high"),
            patch("shared.ai.agent_runtime.AGENT_DISABLE_RESPONSE_STORAGE", True),
        ):
            mock_run.return_value = SimpleNamespace(final_output="OK")
            result = await AgentRuntime().run(
                AgentRunRequest(
                    route="private_chat",
                    user_text="hello",
                    compact_context="",
                    allowed_tool_names=(),
                    trace_id="trace-1",
                )
            )

        self.assertTrue(result.ok)
        model_settings = mock_agent.call_args.kwargs["model_settings"]
        self.assertEqual(model_settings.reasoning.effort, "high")
        self.assertFalse(model_settings.store)

    async def test_passes_max_turns_to_runner(self):
        from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime

        with (
            patch("shared.ai.agent_runtime.build_agent_model_binding", return_value=_binding()),
            patch("shared.ai.agent_runtime.Agent"),
            patch("shared.ai.agent_runtime.Runner.run", new_callable=AsyncMock) as mock_run,
            patch("shared.ai.agent_runtime.AGENT_MAX_TURNS", 5),
        ):
            mock_run.return_value = SimpleNamespace(final_output="OK")
            result = await AgentRuntime().run(
                AgentRunRequest(
                    route="private_chat",
                    user_text="hello",
                    compact_context="",
                    allowed_tool_names=(),
                    trace_id="trace-1",
                )
            )

        self.assertTrue(result.ok)
        self.assertEqual(mock_run.call_args.kwargs["max_turns"], 5)

    async def test_times_out_at_configured_deadline(self):
        from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime

        async def slow_run(*_args, **_kwargs):
            import asyncio

            await asyncio.sleep(0.05)

        with (
            patch("shared.ai.agent_runtime.build_agent_model_binding", return_value=_binding()),
            patch("shared.ai.agent_runtime.Agent"),
            patch("shared.ai.agent_runtime.Runner.run", new=slow_run),
            patch("shared.ai.agent_runtime.AGENT_RUN_TIMEOUT_SECONDS", 0.001),
        ):
            result = await AgentRuntime().run(
                AgentRunRequest(
                    route="private_chat",
                    user_text="hello",
                    compact_context="",
                    allowed_tool_names=(),
                    trace_id=None,
                )
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "timeout")

    async def test_rejects_too_many_requested_tools_before_run(self):
        from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime

        with (
            patch("shared.ai.agent_runtime.Runner.run", new_callable=AsyncMock) as mock_run,
            patch("shared.ai.agent_runtime.AGENT_MAX_TOOL_CALLS", 1),
        ):
            result = await AgentRuntime().run(
                AgentRunRequest(
                    route="private_chat",
                    user_text="open browser",
                    compact_context="",
                    allowed_tool_names=("pc_agent_status", "pc_capture_screen"),
                    trace_id=None,
                )
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "too_many_tools")
        mock_run.assert_not_called()

    async def test_returns_typed_success(self):
        from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime

        with (
            patch("shared.ai.agent_runtime.build_agent_model_binding", return_value=_binding()),
            patch("shared.ai.agent_runtime.Agent"),
            patch("shared.ai.agent_runtime.Runner.run", new_callable=AsyncMock) as mock_run,
        ):
            mock_run.return_value = SimpleNamespace(final_output="**你好**")
            result = await AgentRuntime().run(
                AgentRunRequest(
                    route="private_chat",
                    user_text="hi",
                    compact_context="ctx",
                    allowed_tool_names=(),
                    trace_id="trace-1",
                )
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.output_text, "你好")
        self.assertEqual(result.provider, "responses_proxy")
        self.assertEqual(result.model, "gpt-5.6")

    async def test_returns_typed_provider_failure(self):
        from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime

        with (
            patch("shared.ai.agent_runtime.build_agent_model_binding", return_value=_binding()),
            patch("shared.ai.agent_runtime.Agent"),
            patch("shared.ai.agent_runtime.Runner.run", new_callable=AsyncMock) as mock_run,
            patch("shared.ai.agent_runtime.AGENT_FALLBACK_TO_LEGACY", False),
        ):
            mock_run.side_effect = RuntimeError("provider exploded with sk-secret")
            result = await AgentRuntime().run(
                AgentRunRequest(
                    route="private_chat",
                    user_text="hi",
                    compact_context="ctx",
                    allowed_tool_names=(),
                    trace_id="trace-1",
                )
            )

        self.assertFalse(result.ok)
        self.assertEqual(result.failure_code, "provider_error")
        self.assertNotIn("sk-secret", result.output_text)

    async def test_does_not_persist_an_sdk_session(self):
        from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime

        with (
            patch("shared.ai.agent_runtime.build_agent_model_binding", return_value=_binding()),
            patch("shared.ai.agent_runtime.Agent"),
            patch("shared.ai.agent_runtime.Runner.run", new_callable=AsyncMock) as mock_run,
        ):
            mock_run.return_value = SimpleNamespace(final_output="OK")
            await AgentRuntime().run(
                AgentRunRequest(
                    route="private_chat",
                    user_text="hi",
                    compact_context="ctx",
                    allowed_tool_names=(),
                    trace_id="trace-1",
                )
            )

        self.assertIsNone(mock_run.call_args.kwargs.get("session"))
        self.assertIsNone(mock_run.call_args.kwargs.get("conversation_id"))

    async def test_fallback_is_attempted_at_most_once(self):
        from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime

        legacy_call = MagicMock(return_value="legacy reply")
        with (
            patch("shared.ai.agent_runtime.build_agent_model_binding", return_value=_binding()),
            patch("shared.ai.agent_runtime.Agent"),
            patch("shared.ai.agent_runtime.Runner.run", new_callable=AsyncMock) as mock_run,
            patch("shared.ai.agent_runtime.AGENT_FALLBACK_TO_LEGACY", True),
        ):
            mock_run.side_effect = RuntimeError("provider down")
            result = await AgentRuntime(legacy_call=legacy_call).run(
                AgentRunRequest(
                    route="private_chat",
                    user_text="hi",
                    compact_context="ctx",
                    allowed_tool_names=(),
                    trace_id="trace-1",
                )
            )

        self.assertTrue(result.ok)
        self.assertTrue(result.used_legacy_fallback)
        legacy_call.assert_called_once()


if __name__ == "__main__":
    unittest.main()
