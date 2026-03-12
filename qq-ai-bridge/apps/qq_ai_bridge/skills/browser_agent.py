"""Placeholder skill for future browser automation tasks."""

from __future__ import annotations

from apps.qq_ai_bridge.services.browser_agent_service import build_browser_agent_request
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult


class BrowserAgentSkill:
    """Reserved placeholder for future browser-agent integration."""

    name = "browser_agent"

    def can_handle(self, context: SkillContext) -> bool:
        """Do not intercept production traffic yet."""
        return False

    def handle(self, context: SkillContext) -> SkillResult:
        """Return a placeholder result if explicitly enabled later."""
        _ = build_browser_agent_request("open_url", {"url": "https://example.com"})
        return SkillResult(handled=False, source=self.name, status="ignore")
