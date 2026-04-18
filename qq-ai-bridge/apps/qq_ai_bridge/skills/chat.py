from apps.qq_ai_bridge.services.group_chat_service import enqueue_group_text
from apps.qq_ai_bridge.services.private_chat_service import enqueue_private_text
from apps.qq_ai_bridge.skills.base import Skill, SkillContext, SkillResult


class ChatSkill(Skill):
    name = "chat"

    def can_handle(self, context: SkillContext) -> bool:
        # Default fallback, should always handle
        return True

    def handle(self, context: SkillContext) -> SkillResult:
        query = context.effective_text
        reply_all_messages = context.group_config.get("reply_all_messages", False)
        ai_prefix = str(context.group_config.get("ai_prefix", "")).strip()

        ai_prefix_triggered = False
        if ai_prefix and query.startswith(ai_prefix):
            ai_prefix_triggered = True
            query = query[len(ai_prefix):].strip()

        if context.is_private:
            if not query:
                return SkillResult(handled=True, source=self.name, status="ignore")

            queue_info = enqueue_private_text(
                context.user_id,
                query,
                timestamp=context.timestamp
            )
            context.log(f"[ROUTE] 私聊消息已入队 user_id={context.user_id}")
            return SkillResult(
                handled=True,
                source=self.name,
                response_payload={"status": "enqueued", "queue": queue_info}
            )

        elif context.is_group:
            if not context.should_log and not context.mentioned_self:
                return SkillResult(handled=False, source=self.name, status="ignore")

            if not query:
                return SkillResult(handled=True, source=self.name, status="ignore")

            queue_info = enqueue_group_text(
                context.group_id,
                context.user_id,
                context.nick,
                query,
                group_config=context.group_config,
                explicit_trigger=bool(
                    context.mentioned_self or reply_all_messages or ai_prefix_triggered
                ),
                timestamp=context.timestamp,
                log=context.log,
            )
            context.log(f"[ROUTE] 群聊消息已入队 group_id={context.group_id}")
            return SkillResult(
                handled=True,
                source=self.name,
                response_payload={"status": "enqueued", "queue": queue_info}
            )

        return SkillResult(handled=False, source=self.name, status="ignore")
