"""Skill for understanding uploaded files."""

from __future__ import annotations

from apps.qq_ai_bridge.config.settings import ALLOWED_PRIVATE_USER
from apps.qq_ai_bridge.services.file_service import handle_file_message
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult


class FileUnderstandingSkill:
    """Handle file attachments through the existing file service."""

    name = "file_understanding"

    def can_handle(self, context: SkillContext) -> bool:
        """Only handle messages that carry a file payload."""
        return context.file_info is not None

    def handle(self, context: SkillContext) -> SkillResult:
        """Dispatch file handling while preserving current access rules."""
        if context.is_private:
            if context.user_id != ALLOWED_PRIVATE_USER:
                context.log(f"[FILE] 非授权私聊用户 {context.user_id}，忽略")
                return SkillResult(handled=True, source=self.name, status="ignore")
            payload = handle_file_message(context.message_type, context.user_id, context.group_id, context.file_info)
            return SkillResult(handled=True, source=self.name, response_payload=payload if isinstance(payload, dict) else None)

        if context.is_group:
            if not context.mentioned_self:
                context.log("[FILE] 群聊文件但未 @ 机器人，忽略")
                return SkillResult(handled=True, source=self.name, status="ignore")
            payload = handle_file_message(context.message_type, context.user_id, context.group_id, context.file_info)
            return SkillResult(handled=True, source=self.name, response_payload=payload if isinstance(payload, dict) else None)

        return SkillResult(handled=True, source=self.name, status="ignore")
