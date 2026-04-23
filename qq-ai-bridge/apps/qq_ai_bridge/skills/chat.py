from apps.qq_ai_bridge.services.group_chat_service import enqueue_group_text
from apps.qq_ai_bridge.services.private_chat_service import enqueue_private_text
from apps.qq_ai_bridge.config.settings import GLOBAL_LISTEN_GROUP_IDS
from apps.qq_ai_bridge.skills.base import Skill, SkillContext, SkillResult


class ChatSkill(Skill):
    name = "chat"

    def can_handle(self, context: SkillContext) -> bool:
        # Default fallback, should always handle
        return True

    def handle(self, context: SkillContext) -> SkillResult:
        query = context.effective_text
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

            configured_reply_all = bool(context.group_config.get("reply_all_messages", False))
            fallback_global_listen = int(context.group_id or 0) in GLOBAL_LISTEN_GROUP_IDS
            global_listen = configured_reply_all or fallback_global_listen
            queue_info = enqueue_group_text(
                context.group_id,
                context.user_id,
                context.nick,
                query,
                group_config=context.group_config,
                explicit_trigger=bool(
                    context.mentioned_self or ai_prefix_triggered or global_listen
                ),
                timestamp=context.timestamp,
                message_id=context.data.get("message_id"),
                reply_reference=context.data.get("reply_reference"),
                log=context.log,
            )
            if queue_info.get("queued"):
                context.log(
                    f"[ROUTE] 群聊消息已入队 group_id={context.group_id}"
                    f" explicit_trigger={bool(context.mentioned_self or ai_prefix_triggered or global_listen)}"
                    f" reply_all_messages={bool(context.group_config.get('reply_all_messages', False))}"
                )
            else:
                context.log(
                    f"[ROUTE] 群聊消息未入队 group_id={context.group_id}"
                    f" reason={queue_info.get('reason')}"
                    f" explicit_trigger={bool(context.mentioned_self or ai_prefix_triggered or global_listen)}"
                    f" reply_all_messages={bool(context.group_config.get('reply_all_messages', False))}"
                )
            return SkillResult(
                handled=True,
                source=self.name,
                response_payload={"status": "enqueued", "queue": queue_info}
            )

        return SkillResult(handled=False, source=self.name, status="ignore")
