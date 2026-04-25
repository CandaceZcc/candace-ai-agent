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
        bot_alias_triggered = _is_bot_alias_triggered(query, context.group_config)

        if context.is_private:
            if not query:
                return SkillResult(handled=True, source=self.name, status="ignore")

            queue_info = enqueue_private_text(
                context.user_id,
                query,
                timestamp=context.timestamp,
                message_id=context.data.get("message_id"),
            )
            context.log(f"[ROUTE] 私聊消息已入队 user_id={context.user_id}")
            return SkillResult(
                handled=True,
                source=self.name,
                response_payload={"status": "enqueued", "queue": queue_info}
            )

        elif context.is_group:
            if not context.group_config.get("bot_can_reply", True):
                return SkillResult(handled=True, source=self.name, status="ignore")

            if not query:
                return SkillResult(handled=True, source=self.name, status="ignore")

            configured_reply_all = bool(context.group_config.get("reply_all_messages", False))
            fallback_global_listen = int(context.group_id or 0) in GLOBAL_LISTEN_GROUP_IDS
            global_listen = configured_reply_all or fallback_global_listen
            explicit_trigger = bool(context.mentioned_self or ai_prefix_triggered or bot_alias_triggered)
            if _is_addressed_to_someone_else(context, explicit_trigger=explicit_trigger):
                context.log(
                    f"[ROUTE] 群聊消息未入队 group_id={context.group_id}"
                    f" reason=addressed_to_other"
                    f" explicit_trigger={explicit_trigger}"
                    f" reply_all_messages={bool(context.group_config.get('reply_all_messages', False))}"
                )
                return SkillResult(handled=True, source=self.name, status="ignore")
            queue_info = enqueue_group_text(
                context.group_id,
                context.user_id,
                context.nick,
                query,
                group_config=context.group_config,
                explicit_trigger=explicit_trigger,
                timestamp=context.timestamp,
                message_id=context.data.get("message_id"),
                reply_reference=context.data.get("reply_reference"),
                log=context.log,
            )
            if queue_info.get("queued"):
                context.log(
                    f"[ROUTE] 群聊消息已入队 group_id={context.group_id}"
                    f" explicit_trigger={explicit_trigger}"
                    f" reply_all_messages={bool(context.group_config.get('reply_all_messages', False))}"
                )
            else:
                context.log(
                    f"[ROUTE] 群聊消息未入队 group_id={context.group_id}"
                    f" reason={queue_info.get('reason')}"
                    f" explicit_trigger={explicit_trigger}"
                    f" reply_all_messages={bool(context.group_config.get('reply_all_messages', False))}"
                )
            return SkillResult(
                handled=True,
                source=self.name,
                response_payload={"status": "enqueued", "queue": queue_info}
            )

        return SkillResult(handled=False, source=self.name, status="ignore")


def _is_bot_alias_triggered(text: str, group_config: dict | None) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    aliases = ["机盖宁"]
    configured = (group_config or {}).get("bot_aliases") or []
    if isinstance(configured, str):
        aliases.extend(item.strip() for item in configured.split(",") if item.strip())
    elif isinstance(configured, list):
        aliases.extend(str(item).strip() for item in configured if str(item).strip())
    return any(alias.lower() in normalized for alias in aliases)


def _is_addressed_to_someone_else(context: SkillContext, *, explicit_trigger: bool) -> bool:
    if explicit_trigger:
        return False
    self_id = str(context.self_id or context.data.get("self_id") or "").strip()
    at_targets = [str(item).strip() for item in (context.data.get("at_targets") or []) if str(item).strip()]
    if at_targets:
        return not (self_id and self_id in at_targets)
    reply_reference = context.data.get("reply_reference") or {}
    if not isinstance(reply_reference, dict):
        return False
    sender_id = str(reply_reference.get("sender_id") or "").strip()
    if sender_id:
        return not (self_id and sender_id == self_id)
    if reply_reference.get("message_id") and _looks_like_direct_reply_to_other(context.effective_text):
        return True
    return False


def _looks_like_direct_reply_to_other(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return True
    if len(normalized) <= 24:
        return True
    return any(token in normalized for token in ("你", "你们", "他", "她", "这条", "上面", "刚才"))
