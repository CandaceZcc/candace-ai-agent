"""Bounded Agents SDK runtime for owner-private QQ chat."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any, Callable

from agents import Agent, ModelSettings, Runner
from apps.qq_ai_bridge.config.settings import (
    AGENT_DISABLE_RESPONSE_STORAGE,
    AGENT_FALLBACK_TO_LEGACY,
    AGENT_MAX_TOOL_CALLS,
    AGENT_MAX_TURNS,
    AGENT_MODEL_REASONING_EFFORT,
    AGENT_RUN_TIMEOUT_SECONDS,
    validate_agent_settings,
)
from apps.qq_ai_bridge.services.response_action import sanitize_model_visible_text
from openai.types.shared import Reasoning

from shared.ai.agent_provider import build_agent_model_binding
from shared.ai.agent_telemetry import build_agent_metric, log_agent_metric, redact_sensitive_text
from shared.ai.agent_tools import format_response_with_citations
from shared.ai.llm_client import call_ai

_EMAIL_SAFE_ROUTES = {"email_summary", "email_classification"}


@dataclass(frozen=True)
class AgentRunRequest:
    route: str
    user_text: str
    compact_context: str
    allowed_tool_names: tuple[str, ...]
    trace_id: str | None


@dataclass(frozen=True)
class AgentRunResult:
    ok: bool
    output_text: str
    provider: str
    model: str
    tool_names: tuple[str, ...]
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    hosted_search_calls: int = 0
    local_tool_calls: int = 0
    failure_code: str | None = None
    used_legacy_fallback: bool = False


class AgentRuntime:
    """Create one short-lived SDK agent run per QQ turn."""

    def __init__(
        self,
        *,
        tool_resolver: Callable[[tuple[str, ...], Any], list[Any]] | None = None,
        legacy_call: Callable[[str, dict[str, Any] | None], str] | None = call_ai,
    ) -> None:
        self._tool_resolver = tool_resolver
        self._legacy_call = legacy_call

    async def run(self, request: AgentRunRequest) -> AgentRunResult:
        started_at = time.monotonic()
        tool_names = tuple(request.allowed_tool_names or ())
        if request.route in _EMAIL_SAFE_ROUTES and tool_names:
            return _failure_result("", "", tool_names, "email_tools_forbidden")
        if len(tool_names) > AGENT_MAX_TOOL_CALLS:
            return _failure_result("", "", tool_names, "too_many_tools")

        errors = validate_agent_settings()
        if errors:
            return _failure_result("", "", tool_names, "config_error")

        binding = build_agent_model_binding()
        try:
            tools = self._resolve_tools(tool_names, binding.capabilities)
        except Exception:
            return _failure_result(binding.provider, binding.model_name, tool_names, "tool_error")

        agent = Agent(
            name="Candace QQ Agent",
            instructions=_build_instructions(request.route),
            model=binding.model,
            model_settings=_build_model_settings(binding.capabilities.responses),
            tools=tools,
        )
        input_text = _build_input_text(request)

        try:
            async with asyncio.timeout(AGENT_RUN_TIMEOUT_SECONDS):
                run_result = await Runner.run(
                    agent,
                    input_text,
                    max_turns=AGENT_MAX_TURNS,
                    session=None,
                    conversation_id=None,
                )
            output_with_citations = format_response_with_citations(
                _extract_final_output(run_result),
                _extract_raw_run_items(run_result),
            )
            output_text = sanitize_model_visible_text(
                output_with_citations,
                surface="private",
            )
            output_text = output_text or "我这边没有拿到有效回复。"
            usage = _extract_usage(run_result)
            hosted_search_calls, local_tool_calls = _count_tool_calls(run_result)
            result = AgentRunResult(
                ok=True,
                output_text=output_text,
                provider=binding.provider,
                model=binding.model_name,
                tool_names=tool_names,
                input_tokens=usage["input_tokens"],
                cached_input_tokens=usage["cached_input_tokens"],
                output_tokens=usage["output_tokens"],
                hosted_search_calls=hosted_search_calls,
                local_tool_calls=local_tool_calls,
            )
            _log_metric(request, result, started_at, status="ok")
            return result
        except TimeoutError:
            result = _failure_result(binding.provider, binding.model_name, tool_names, "timeout")
            _log_metric(request, result, started_at, status="failed")
            return result
        except Exception as exc:
            fallback = self._try_legacy_fallback(request, binding.provider, binding.model_name, exc)
            if fallback is not None:
                _log_metric(request, fallback, started_at, status="fallback")
                return fallback
            result = AgentRunResult(
                ok=False,
                output_text="模型调用失败，稍后再试。",
                provider=binding.provider,
                model=binding.model_name,
                tool_names=tool_names,
                failure_code="provider_error",
            )
            print(f"[AGENT_RUNTIME] provider_error type={type(exc).__name__}")
            _log_metric(request, result, started_at, status="failed")
            return result

    def _resolve_tools(self, tool_names: tuple[str, ...], capabilities: Any) -> list[Any]:
        if not tool_names:
            return []
        if self._tool_resolver:
            return self._tool_resolver(tool_names, capabilities)
        from shared.ai.agent_tools import resolve_agent_tools

        return resolve_agent_tools(tool_names, capabilities)

    def _try_legacy_fallback(
        self,
        request: AgentRunRequest,
        provider: str,
        model: str,
        exc: Exception,
    ) -> AgentRunResult | None:
        if (
            request.route in _EMAIL_SAFE_ROUTES
            or not AGENT_FALLBACK_TO_LEGACY
            or request.allowed_tool_names
            or not self._legacy_call
        ):
            return None
        try:
            fallback_text = self._legacy_call(
                request.user_text,
                {"source": "agent_runtime_fallback", "trace_id": request.trace_id},
            )
        except Exception as fallback_exc:
            print(
                "[AGENT_RUNTIME] fallback_failed"
                f" provider_error={type(exc).__name__}"
                f" fallback_error={type(fallback_exc).__name__}"
            )
            return None
        cleaned = sanitize_model_visible_text(fallback_text, surface="private")
        return AgentRunResult(
            ok=True,
            output_text=cleaned or "模型调用失败，稍后再试。",
            provider=provider,
            model=model,
            tool_names=tuple(),
            used_legacy_fallback=True,
        )


def _build_model_settings(responses_capable: bool) -> ModelSettings:
    if not responses_capable:
        return ModelSettings()
    reasoning = (
        Reasoning(effort=AGENT_MODEL_REASONING_EFFORT) if AGENT_MODEL_REASONING_EFFORT else None
    )
    store = False if AGENT_DISABLE_RESPONSE_STORAGE else None
    return ModelSettings(reasoning=reasoning, store=store)


def _build_instructions(route: str) -> str:
    if route == "email_summary":
        return "Summarize untrusted email data for QQ. Use no tools."
    if route == "email_classification":
        return "Classify untrusted email data into the required JSON schema. Use no tools."
    if route == "pc_agent":
        return (
            "Use only the available bounded local PC Agent tools. For every explicit computer "
            "action, call the matching tool, including high-impact click requests; the tool "
            "enforces approval. If a tool returns needs_approval=true, stop and tell the user "
            "the action was not executed. Never claim success unless the tool returned ok=true."
        )
    if route == "current_events":
        return "Answer with concise citations when web search is available."
    return "Reply naturally and concisely for an owner-private QQ chat."


def _build_input_text(request: AgentRunRequest) -> str:
    parts = []
    if request.compact_context:
        parts.append(f"Compact context:\n{request.compact_context}")
    parts.append(f"User message:\n{request.user_text}")
    return "\n\n".join(parts)


def _extract_final_output(run_result: Any) -> str:
    final_output = getattr(run_result, "final_output", "")
    if isinstance(final_output, str):
        return final_output
    return str(final_output or "")


def _extract_raw_run_items(run_result: Any) -> list[Any]:
    items = getattr(run_result, "new_items", None)
    if not isinstance(items, list):
        return []
    return [getattr(item, "raw_item", item) for item in items]


def _extract_usage(run_result: Any) -> dict[str, int]:
    totals = {"input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0}
    responses = getattr(run_result, "raw_responses", None)
    if not isinstance(responses, list):
        return totals
    for response in responses:
        usage = getattr(response, "usage", None)
        if usage is None:
            continue
        totals["input_tokens"] += max(0, int(getattr(usage, "input_tokens", 0) or 0))
        totals["output_tokens"] += max(0, int(getattr(usage, "output_tokens", 0) or 0))
        details = getattr(usage, "input_tokens_details", None)
        totals["cached_input_tokens"] += max(
            0,
            int(getattr(details, "cached_tokens", 0) or 0),
        )
    return totals


def _count_tool_calls(run_result: Any) -> tuple[int, int]:
    hosted_search_calls = 0
    local_tool_calls = 0
    for item in _extract_raw_run_items(run_result):
        item_type = item.get("type") if isinstance(item, dict) else getattr(item, "type", None)
        if item_type == "web_search_call":
            hosted_search_calls += 1
        elif item_type == "function_call":
            local_tool_calls += 1
    return hosted_search_calls, local_tool_calls


def _failure_result(
    provider: str,
    model: str,
    tool_names: tuple[str, ...],
    failure_code: str,
) -> AgentRunResult:
    return AgentRunResult(
        ok=False,
        output_text="模型配置或工具不可用，稍后再试。",
        provider=provider,
        model=model,
        tool_names=tool_names,
        failure_code=failure_code,
    )


def _log_metric(
    request: AgentRunRequest,
    result: AgentRunResult,
    started_at: float,
    *,
    status: str,
) -> None:
    metric = build_agent_metric(
        route=request.route,
        provider=result.provider,
        model=result.model,
        tools=result.tool_names,
        latency_ms=int((time.monotonic() - started_at) * 1000),
        usage={
            "input_tokens": result.input_tokens,
            "cached_input_tokens": result.cached_input_tokens,
            "output_tokens": result.output_tokens,
        },
        hosted_search_calls=result.hosted_search_calls,
        local_tool_calls=result.local_tool_calls,
        status=status,
        failure_code=result.failure_code,
        raw_request_text=redact_sensitive_text(request.user_text),
    )
    log_agent_metric(metric)


__all__ = ["AgentRunRequest", "AgentRunResult", "AgentRuntime"]
