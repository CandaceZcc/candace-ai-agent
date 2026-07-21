"""Capability probes for OpenAI Responses-compatible agent providers."""

from dataclasses import dataclass
from typing import Any, Literal

import requests
from apps.qq_ai_bridge.config.settings import (
    AGENT_DISABLE_RESPONSE_STORAGE,
    AGENT_MODEL_REASONING_EFFORT,
    CHAT_COMPATIBLE_BASE_URL,
    CHAT_COMPATIBLE_MODEL,
    OPENAI_AGENT_MODEL,
    OPENAI_API_KEY,
    RESPONSES_PROXY_API_KEY,
    RESPONSES_PROXY_BASE_URL,
    RESPONSES_PROXY_MODEL,
)

from shared.ai.agent_provider import ProviderCapabilities, ProviderName

ProbeName = Literal["text", "web_search", "computer"]


@dataclass(frozen=True)
class CapabilityProbeResult:
    supported: bool
    exit_code: int
    provider: ProviderName
    probe: ProbeName
    capabilities: ProviderCapabilities
    message: str


def interpret_probe_response(
    *,
    provider: ProviderName,
    probe: ProbeName,
    status_code: int,
    payload: dict[str, Any] | None = None,
    response_text: str = "",
) -> CapabilityProbeResult:
    """Interpret a synthetic or live probe response without exposing upstream details."""
    capabilities = _empty_capabilities(provider)
    if provider == "chat_compatible" and probe in {"web_search", "computer"}:
        return _unsupported(provider, probe, capabilities, "chat_compatible skips hosted probes")

    if status_code in {401, 403}:
        return _failure(provider, probe, capabilities, "authentication or authorization failed")
    if status_code < 200 or status_code >= 300:
        return _failure(provider, probe, capabilities, f"upstream error {status_code}")

    output_items = _output_items(payload or {})
    if probe == "text":
        if _has_message_text(output_items):
            return _supported(
                provider,
                probe,
                ProviderCapabilities(
                    responses=True,
                    function_tools=True,
                    hosted_web_search=False,
                    builtin_computer=False,
                    openai_trace_export=(provider == "openai"),
                    verified=True,
                ),
                "Responses text probe passed",
            )
        return _unsupported(provider, probe, capabilities, "Responses text output was missing")

    if probe == "web_search":
        if _has_item_type(output_items, "web_search_call") and _has_url_citation(output_items):
            return _supported(
                provider,
                probe,
                ProviderCapabilities(
                    responses=True,
                    function_tools=True,
                    hosted_web_search=True,
                    builtin_computer=False,
                    openai_trace_export=(provider == "openai"),
                    verified=True,
                ),
                "web_search_call probe passed",
            )
        return _unsupported(
            provider,
            probe,
            capabilities,
            "web_search_call with URL citation was not returned",
        )

    if probe == "computer":
        if _has_item_type(output_items, "computer_call"):
            return _supported(
                provider,
                probe,
                ProviderCapabilities(
                    responses=True,
                    function_tools=True,
                    hosted_web_search=False,
                    builtin_computer=True,
                    openai_trace_export=(provider == "openai"),
                    verified=True,
                ),
                "computer_call probe passed without executing actions",
            )
        return _unsupported(provider, probe, capabilities, "computer_call was not returned")

    return _unsupported(provider, probe, capabilities, "unknown probe")


def run_probe(
    *,
    provider: ProviderName,
    probe: ProbeName,
    accept_billable_probe: bool = False,
    post=requests.post,
    timeout_seconds: int = 30,
) -> CapabilityProbeResult:
    """Run one live probe. Hosted-tool probes require explicit billable acceptance."""
    if probe in {"web_search", "computer"} and not accept_billable_probe:
        return _failure(
            provider,
            probe,
            _empty_capabilities(provider),
            "billable hosted-tool probe requires --accept-billable-probe",
            exit_code=2,
        )
    if provider == "chat_compatible" and probe in {"web_search", "computer"}:
        return interpret_probe_response(
            provider=provider,
            probe=probe,
            status_code=200,
            payload={},
        )

    try:
        response = post(
            _responses_url(provider),
            headers=_headers(provider),
            json=_build_payload(provider, probe),
            timeout=timeout_seconds,
        )
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        return interpret_probe_response(
            provider=provider,
            probe=probe,
            status_code=response.status_code,
            payload=payload,
            response_text=getattr(response, "text", ""),
        )
    except requests.RequestException:
        return _failure(provider, probe, _empty_capabilities(provider), "network failure")


def _build_payload(provider: ProviderName, probe: ProbeName) -> dict[str, Any]:
    model = _model_for_provider(provider)
    if probe == "text":
        payload = {
            "model": model,
            "input": "Reply with exactly OK.",
            "max_output_tokens": 32,
        }
    elif probe == "web_search":
        payload = {
            "model": model,
            "input": "What is the title of the current OpenAI API documentation home page?",
            "tools": [{"type": "web_search_preview", "search_context_size": "low"}],
            "max_output_tokens": 256,
        }
    else:
        payload = {
            "model": model,
            "input": "Observe the screen and return one computer_call. Do not execute anything.",
            "tools": [
                {
                    "type": "computer_use_preview",
                    "display_width": 1024,
                    "display_height": 768,
                    "environment": "browser",
                }
            ],
            "max_output_tokens": 256,
        }
    if provider in {"openai", "responses_proxy"}:
        if AGENT_MODEL_REASONING_EFFORT:
            payload["reasoning"] = {"effort": AGENT_MODEL_REASONING_EFFORT}
        if AGENT_DISABLE_RESPONSE_STORAGE:
            payload["store"] = False
    return payload


def _responses_url(provider: ProviderName) -> str:
    if provider == "openai":
        return "https://api.openai.com/v1/responses"
    if provider == "responses_proxy":
        return f"{RESPONSES_PROXY_BASE_URL.rstrip('/')}/responses"
    return f"{CHAT_COMPATIBLE_BASE_URL.rstrip('/')}/responses"


def _headers(provider: ProviderName) -> dict[str, str]:
    return {
        "Authorization": f"Bearer {_api_key_for_provider(provider)}",
        "Content-Type": "application/json",
    }


def _api_key_for_provider(provider: ProviderName) -> str:
    if provider == "openai":
        return OPENAI_API_KEY
    if provider == "responses_proxy":
        return RESPONSES_PROXY_API_KEY
    return ""


def _model_for_provider(provider: ProviderName) -> str:
    if provider == "openai":
        return OPENAI_AGENT_MODEL
    if provider == "responses_proxy":
        return RESPONSES_PROXY_MODEL
    return CHAT_COMPATIBLE_MODEL


def _output_items(payload: dict[str, Any]) -> list[dict[str, Any]]:
    output = payload.get("output")
    if isinstance(output, list):
        return [item for item in output if isinstance(item, dict)]
    return []


def _has_item_type(items: list[dict[str, Any]], item_type: str) -> bool:
    return any(item.get("type") == item_type for item in items)


def _has_message_text(items: list[dict[str, Any]]) -> bool:
    for item in items:
        for part in _content_parts(item):
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return True
    return False


def _has_url_citation(items: list[dict[str, Any]]) -> bool:
    for item in items:
        for part in _content_parts(item):
            for annotation in part.get("annotations") or []:
                if isinstance(annotation, dict) and str(annotation.get("url") or "").startswith(
                    "https://"
                ):
                    return True
    return False


def _content_parts(item: dict[str, Any]) -> list[dict[str, Any]]:
    content = item.get("content")
    if not isinstance(content, list):
        return []
    return [part for part in content if isinstance(part, dict)]


def _empty_capabilities(provider: ProviderName) -> ProviderCapabilities:
    return ProviderCapabilities(
        responses=False,
        function_tools=(provider == "chat_compatible"),
        hosted_web_search=False,
        builtin_computer=False,
        openai_trace_export=False,
        verified=False,
    )


def _supported(
    provider: ProviderName,
    probe: ProbeName,
    capabilities: ProviderCapabilities,
    message: str,
) -> CapabilityProbeResult:
    return CapabilityProbeResult(
        supported=True,
        exit_code=0,
        provider=provider,
        probe=probe,
        capabilities=capabilities,
        message=message,
    )


def _unsupported(
    provider: ProviderName,
    probe: ProbeName,
    capabilities: ProviderCapabilities,
    message: str,
) -> CapabilityProbeResult:
    return CapabilityProbeResult(
        supported=False,
        exit_code=2,
        provider=provider,
        probe=probe,
        capabilities=capabilities,
        message=message,
    )


def _failure(
    provider: ProviderName,
    probe: ProbeName,
    capabilities: ProviderCapabilities,
    message: str,
    exit_code: int = 1,
) -> CapabilityProbeResult:
    return CapabilityProbeResult(
        supported=False,
        exit_code=exit_code,
        provider=provider,
        probe=probe,
        capabilities=capabilities,
        message=message,
    )


__all__ = [
    "CapabilityProbeResult",
    "ProbeName",
    "interpret_probe_response",
    "run_probe",
]
