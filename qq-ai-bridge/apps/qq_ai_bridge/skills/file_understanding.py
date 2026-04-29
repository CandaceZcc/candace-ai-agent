
from apps.qq_ai_bridge.config.settings import ALLOWED_PRIVATE_USER
from apps.qq_ai_bridge.services.file_service import handle_file_message
from apps.qq_ai_bridge.skills.base import Skill, SkillContext, SkillResult


class FileUnderstandingSkill(Skill):
    name = "file_understanding"

    def can_handle(self, context: SkillContext) -> bool:
        return context.file_info is not None

    def handle(self, context: SkillContext) -> SkillResult:
        if context.is_private:
            if context.user_id != ALLOWED_PRIVATE_USER:
                context.log(f"[FILE] 非授权私聊用户 {context.user_id}，忽略")
                return SkillResult(handled=True, source=self.name, status="ignore")

            payload = handle_file_message(
                context.message_type, context.user_id, context.group_id, context.file_info
            )
            return SkillResult(
                handled=True,
                source=self.name,
                response_payload=payload if isinstance(payload, dict) else None
            )

        if context.is_group:
            context.log("[FILE] 群聊文件忽略，仅私聊读取")
            return SkillResult(handled=True, source=self.name, status="ignore")

        return SkillResult(handled=True, source=self.name, status="ignore")
