"""Skill for private desktop-agent commands."""

from __future__ import annotations

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import ALLOWED_PRIVATE_USER
from apps.qq_ai_bridge.services.agent_service import handle_pc_agent_command
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult


class DesktopAgentSkill:
    """Handle owner-only `agent ...` desktop automation commands."""

    name = "desktop_agent"

    def match_reason(self, context: SkillContext) -> str:
        """Return human-readable match reason for debug logs."""
        if not context.is_private:
            return "not_private"
        if context.user_id != ALLOWED_PRIVATE_USER:
            return "not_owner"
        if not context.normalized_msg.startswith("agent "):
            return "missing_agent_prefix"
        return "owner_private_agent_command"

    def can_handle(self, context: SkillContext) -> bool:
        """Only handle explicit owner desktop commands."""
        return self.match_reason(context) == "owner_private_agent_command"

    def handle(self, context: SkillContext) -> SkillResult:
        """Execute the existing desktop-agent command path if matched."""
        reply = handle_pc_agent_command(context.normalized_msg, context.user_id)
        if reply is None:
            return SkillResult(handled=False, source=self.name, status="ignore")
        send_private_msg(context.user_id, reply)
        return SkillResult(handled=True, source=self.name, response_payload={"status": "ok", "source": "pc_agent"})
