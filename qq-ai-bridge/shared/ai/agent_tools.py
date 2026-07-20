"""Selective tool registry for Agents SDK runs."""

from __future__ import annotations

from typing import Any

from agents import WebSearchTool

from apps.qq_ai_bridge.config.settings import OPENAI_HOSTED_WEB_SEARCH_ENABLED
from shared.ai.agent_provider import ProviderCapabilities


class CapabilityUnavailable(Exception):
    """Raised when a requested tool is disabled or unsupported."""


def resolve_agent_tools(
    tool_names: tuple[str, ...] | list[str],
    capabilities: ProviderCapabilities,
) -> list[Any]:
    """Return SDK tools for exactly the requested names."""
    tools: list[Any] = []
    for name in tool_names:
        if name == "web_search":
            tools.append(_build_web_search_tool(capabilities))
            continue
        if name.startswith("pc_"):
            tools.append(_build_pc_agent_tool(name, capabilities))
            continue
        raise CapabilityUnavailable(f"unsupported agent tool: {name}")
    return tools


def _build_web_search_tool(capabilities: ProviderCapabilities) -> WebSearchTool:
    if not OPENAI_HOSTED_WEB_SEARCH_ENABLED:
        raise CapabilityUnavailable("hosted web search is disabled")
    if not capabilities.responses:
        raise CapabilityUnavailable("provider does not support Responses hosted tools")
    if not capabilities.hosted_web_search or not capabilities.verified:
        raise CapabilityUnavailable("hosted web search capability is not verified")
    return WebSearchTool(search_context_size="low")


def _build_pc_agent_tool(name: str, capabilities: ProviderCapabilities) -> Any:
    if not capabilities.function_tools:
        raise CapabilityUnavailable("provider does not support local function tools")
    from shared.ai.pc_agent_tools import get_pc_agent_tool

    try:
        return get_pc_agent_tool(name)
    except ValueError as exc:
        raise CapabilityUnavailable(str(exc)) from exc


def format_response_with_citations(
    answer_text: str,
    response_items: list[Any] | tuple[Any, ...],
    *,
    max_sources: int = 5,
) -> str:
    """Append QQ-visible URL citations extracted from SDK response items."""
    answer = str(answer_text or "").strip()
    citations = _extract_url_citations(response_items, max_sources=max_sources)
    if not citations:
        return answer
    lines = [answer, "", "来源："] if answer else ["来源："]
    for idx, citation in enumerate(citations, start=1):
        lines.append(f"[{idx}] {citation['title']} - {citation['url']}")
    return "\n".join(lines).strip()


def _extract_url_citations(
    response_items: list[Any] | tuple[Any, ...],
    *,
    max_sources: int,
) -> list[dict[str, str]]:
    seen: set[str] = set()
    citations: list[dict[str, str]] = []
    for item in response_items or ():
        for part in _content_parts(item):
            annotations = _get_value(part, "annotations") or []
            for annotation in annotations:
                url = str(_get_value(annotation, "url") or "").strip()
                if not url.startswith("https://") or url in seen:
                    continue
                title = str(_get_value(annotation, "title") or url).strip()
                citations.append({"title": title, "url": url})
                seen.add(url)
                if len(citations) >= max_sources:
                    return citations
    return citations


def _content_parts(item: Any) -> list[Any]:
    content = _get_value(item, "content")
    if isinstance(content, list):
        return content
    return []


def _get_value(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


__all__ = [
    "CapabilityUnavailable",
    "format_response_with_citations",
    "resolve_agent_tools",
]
