"""Placeholder skill for future browser automation tasks."""

from __future__ import annotations

from apps.qq_ai_bridge.adapters.napcat_client import send_group_msg, send_private_msg
from apps.qq_ai_bridge.services.browser_agent_service import build_browser_agent_request
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult


class BrowserAgentSkill:
    """Reserved placeholder for future browser-agent integration."""

    name = "browser_agent"

    def match_reason(self, context: SkillContext) -> str:
        """Return human-readable match reason for debug logs."""
        text = context.normalized_msg.lower().strip()
        explicit = text.startswith("browser ") or text.startswith("/browser ")
        if not explicit:
            return "missing_browser_prefix"

        if context.is_private:
            return "explicit_private_browser_command"

        if context.is_group:
            if not context.group_config.get("bot_can_reply", True):
                return "group_reply_disabled"
            reply_all_messages = context.group_config.get("reply_all_messages", False)
            if context.mentioned_self or reply_all_messages:
                return "explicit_group_browser_command"
            return "group_not_triggered"

        return "unsupported_message_type"

    def can_handle(self, context: SkillContext) -> bool:
        """Only handle explicit browser-prefixed commands."""
        return self.match_reason(context) in {
            "explicit_private_browser_command",
            "explicit_group_browser_command",
        }

    def handle(self, context: SkillContext) -> SkillResult:
        """Return a placeholder response and keep browser flow isolated for now."""
        _ = build_browser_agent_request("open_url", {"url": "https://example.com"})
        msg = "browser agent 已匹配，但当前仍是占位模式，暂未接入生产执行。"
        if context.is_private:
            send_private_msg(context.user_id, msg)
            return SkillResult(handled=True, source=self.name, response_payload={"status": "ok", "source": self.name})
        if context.is_group:
            send_group_msg(context.group_id, msg, quiet=not context.should_log)
            return SkillResult(handled=True, source=self.name, response_payload={"status": "ok", "source": self.name})
        return SkillResult(handled=False, source=self.name, status="ignore")
