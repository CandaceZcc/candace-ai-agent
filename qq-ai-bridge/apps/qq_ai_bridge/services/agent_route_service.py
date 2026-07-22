"""Deterministic route selection for owner-private agent canaries."""

from __future__ import annotations

import re
from dataclasses import dataclass

_CURRENT_EVENT_TOKENS = (
    "今天",
    "现在",
    "最新",
    "当前",
    "刚刚",
    "新闻",
    "current",
    "latest",
    "today",
    "now",
)
_SEARCH_INTENT_TOKENS = (
    "查一下",
    "查查",
    "搜索",
    "搜一下",
    "lookup",
    "search",
    "what happened",
)
_PC_AGENT_PREFIX_RE = re.compile(r"^\s*(?:agent|/agent|browser|/browser)\b", re.IGNORECASE)
_PC_AGENT_TOKENS = (
    "打开网页",
    "打开网站",
    "浏览器",
    "pc agent",
    "电脑",
)
_EMAIL_COMMAND_RE = re.compile(r"^\s*邮件(?:\s+|$)")


@dataclass(frozen=True)
class AgentRouteDecision:
    route: str
    allowed_tool_names: tuple[str, ...]
    use_general_agent: bool = True


def classify_agent_route(text: str) -> AgentRouteDecision:
    """Classify an owner-private message without calling a model."""
    normalized = str(text or "").strip()
    lowered = normalized.lower()
    if not normalized:
        return AgentRouteDecision("private_chat", ())
    if _EMAIL_COMMAND_RE.match(normalized):
        return AgentRouteDecision("email_command", (), use_general_agent=False)
    if _looks_like_pc_agent_request(normalized, lowered):
        return AgentRouteDecision(
            "pc_agent",
            (
                "pc_agent_status",
                "pc_open_http_url",
                "pc_capture_screen",
                "pc_browser_inspect",
                "pc_browser_click_text",
            ),
        )
    if _looks_like_current_events_request(normalized, lowered):
        return AgentRouteDecision("current_events", ("web_search",))
    return AgentRouteDecision("private_chat", ())


def _looks_like_pc_agent_request(text: str, lowered: str) -> bool:
    if _PC_AGENT_PREFIX_RE.search(text):
        return True
    return any(token in lowered for token in _PC_AGENT_TOKENS)


def _looks_like_current_events_request(text: str, lowered: str) -> bool:
    has_freshness = any(token in lowered or token in text for token in _CURRENT_EVENT_TOKENS)
    has_search = any(token in lowered or token in text for token in _SEARCH_INTENT_TOKENS)
    return has_freshness and has_search


__all__ = ["AgentRouteDecision", "classify_agent_route"]
