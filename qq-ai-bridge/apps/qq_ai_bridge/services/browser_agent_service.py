"""Minimal service boundary for future browser-agent integration."""

from __future__ import annotations

import os
from typing import Any


def get_browser_agent_endpoint() -> str:
    """Return the browser-agent endpoint base URL for future integration."""
    return os.environ.get("PC_BROWSER_AGENT_URL", "http://127.0.0.1:5050/browser")


def build_browser_agent_request(action: str, params: dict | None = None) -> dict[str, Any]:
    """Build a normalized request payload for the future browser runtime."""
    return {"action": action, "params": params or {}, "endpoint": get_browser_agent_endpoint()}


__all__ = ["get_browser_agent_endpoint", "build_browser_agent_request"]
