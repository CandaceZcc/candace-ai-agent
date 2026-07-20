"""Redacted telemetry helpers for Agents SDK runs."""

from __future__ import annotations

import json
import re
from typing import Any

_API_KEY_RE = re.compile(r"\b(?:sk|rk|ak)-[A-Za-z0-9_-]{8,}\b")
_AUTH_RE = re.compile(r"(?i)(Authorization\s*:\s*Bearer\s+)[^\s]+")
_PASSWORD_ASSIGNMENT_RE = re.compile(
    r"(?i)(EMAIL_IMAP_PASSWORD\s*=\s*|password\s*=\s*)[^\s]+"
)
_EMAIL_BODY_TAG_RE = re.compile(
    r"(?is)<email_body\b[^>]*>.*?</email_body>"
)


def redact_sensitive_text(value: Any) -> str:
    """Redact credentials and explicit email-body samples from diagnostic text."""
    text = str(value or "")
    text = _AUTH_RE.sub(r"\1[REDACTED]", text)
    text = _PASSWORD_ASSIGNMENT_RE.sub(r"\1[REDACTED]", text)
    text = _API_KEY_RE.sub("[REDACTED]", text)
    text = _EMAIL_BODY_TAG_RE.sub("<email_body>[REDACTED]</email_body>", text)
    return text


def build_agent_metric(
    *,
    route: str,
    provider: str,
    model: str,
    tools: tuple[str, ...] | list[str],
    latency_ms: int,
    usage: dict[str, Any] | None,
    hosted_search_calls: int,
    local_tool_calls: int,
    status: str,
    failure_code: str | None,
    raw_request_text: str | None = None,
) -> dict[str, Any]:
    """Build a safe operational metric. Raw request text is intentionally ignored."""
    usage = usage or {}
    return {
        "route": str(route or ""),
        "provider": str(provider or ""),
        "model": str(model or ""),
        "tools": list(tools or ()),
        "latency_ms": max(0, int(latency_ms or 0)),
        "input_tokens": int(usage.get("input_tokens") or usage.get("prompt_tokens") or 0),
        "cached_input_tokens": int(usage.get("cached_input_tokens") or 0),
        "output_tokens": int(usage.get("output_tokens") or usage.get("completion_tokens") or 0),
        "hosted_search_calls": max(0, int(hosted_search_calls or 0)),
        "local_tool_calls": max(0, int(local_tool_calls or 0)),
        "status": str(status or "unknown"),
        "failure_code": failure_code,
    }


def log_agent_metric(metric: dict[str, Any]) -> None:
    """Print one redacted JSON metric line for local operational logs."""
    print("[AGENT_METRIC] " + redact_sensitive_text(json.dumps(metric, ensure_ascii=False)))


__all__ = ["build_agent_metric", "log_agent_metric", "redact_sensitive_text"]
