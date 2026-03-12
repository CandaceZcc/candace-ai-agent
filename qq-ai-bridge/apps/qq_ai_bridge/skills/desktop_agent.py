"""Skill for private desktop-agent commands."""

from __future__ import annotations

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import ALLOWED_PRIVATE_USER
from apps.qq_ai_bridge.services.agent_service import handle_pc_agent_command
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult


class DesktopAgentSkill:
    """Handle owner-only `agent ...` desktop automation commands."""

    name = "desktop_agent"

    def can_handle(self, context: SkillContext) -> bool:
        """Only handle owner private messages."""
        return context.is_private and context.user_id == ALLOWED_PRIVATE_USER

    def handle(self, context: SkillContext) -> SkillResult:
        """Execute the existing desktop-agent command path if matched."""
        reply = handle_pc_agent_command(context.normalized_msg, context.user_id)
        if reply is None:
            return SkillResult(handled=False, source=self.name, status="ignore")
        send_private_msg(context.user_id, reply)
        return SkillResult(handled=True, source=self.name, response_payload={"status": "ok", "source": "pc_agent"})
