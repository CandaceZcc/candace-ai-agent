"""Chat skill for private and group text conversations."""

from __future__ import annotations

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text
from apps.qq_ai_bridge.config.settings import ALLOWED_PRIVATE_USER
from apps.qq_ai_bridge.services.group_chat_service import enqueue_group_text
from apps.qq_ai_bridge.services.private_chat_service import enqueue_private_text
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult


class ChatSkill:
    """Default text chat skill."""

    name = "chat"

    def match_reason(self, context: SkillContext) -> str:
        """Return human-readable match reason for debug logs."""
        if context.is_private:
            return "private_text_fallback"
        if context.is_group:
            return "group_text_fallback"
        return "unsupported_message_type"

    def can_handle(self, context: SkillContext) -> bool:
        """Chat remains the fallback skill for text messages."""
        return context.is_private or context.is_group

    def handle(self, context: SkillContext) -> SkillResult:
        """Handle private or group text chat flow."""
        if context.is_private:
            context.log("[ROUTE] 进入私聊分支")
            query = context.effective_text
            context.log(f"[ROUTE] effective_query={query!r}")
            if query == "":
                context.log("[ROUTE] 私聊无有效文本内容，忽略")
                return SkillResult(handled=True, source=self.name, status="ignore")
            context.log(f"[ROUTE] 私聊 query = {query!r}")

            if context.user_id == ALLOWED_PRIVATE_USER and query.startswith("agent "):
                context.log("[ROUTE] 私聊命中 agent 命令，交给 desktop_agent")
                return SkillResult(handled=False, source=self.name, status="ignore")

            if query.startswith("ai "):
                ai_query = normalize_query_text(query[3:])
            else:
                ai_query = query

            if ai_query == "":
                context.log("[ROUTE] 私聊文本清洗后为空，忽略")
                return SkillResult(handled=True, source=self.name, status="ignore")

            queue_info = enqueue_private_text(context.user_id, ai_query, timestamp=context.timestamp)
            context.log(
                f"[ROUTE] 私聊消息已入队 user_id={context.user_id}"
                f" pending_count={queue_info.get('pending_count')}"
            )
            return SkillResult(
                handled=True,
                source=self.name,
                response_payload={"status": "ok", "source": self.name, **queue_info},
            )

        context.log("[ROUTE] 进入群聊分支")
        if not context.group_config.get("bot_can_reply", True):
            context.log("[ROUTE] 群配置禁止回复，忽略")
            return SkillResult(handled=True, source=self.name, status="ignore")

        reply_all_messages = context.group_config.get("reply_all_messages", False)
        query = context.effective_text
        context.log(f"[ROUTE] effective_query={query!r}")
        if query == "":
            context.log("[ROUTE] 群聊无有效文本内容，忽略")
            return SkillResult(handled=True, source=self.name, status="ignore")
        ai_prefix_triggered = query.startswith("ai ")
        if ai_prefix_triggered:
            query = normalize_query_text(query[3:])
        if query == "":
            context.log("[ROUTE] 群聊文本去掉 ai 前缀后为空，忽略")
            return SkillResult(handled=True, source=self.name, status="ignore")
        context.log(f"[ROUTE] 群聊 query = {query!r}")

        queue_info = enqueue_group_text(
            context.group_id,
            context.user_id,
            _extract_sender_name(context),
            query,
            group_config=context.group_config,
            explicit_trigger=bool(context.mentioned_self or reply_all_messages or ai_prefix_triggered),
            timestamp=context.timestamp,
            log=context.log,
        )
        if not queue_info.get("queued"):
            context.log(f"[ROUTE] 群聊未入队 reason={queue_info.get('reason')}")
            return SkillResult(handled=True, source=self.name, status="ignore")

        return SkillResult(
            handled=True,
            source=self.name,
            response_payload={"status": "ok", "source": self.name, **queue_info},
        )


def _extract_sender_name(context: SkillContext) -> str:
    sender = context.data.get("sender", {}) if isinstance(context.data, dict) else {}
    if isinstance(sender, dict):
        for key in ("card", "nickname", "nick", "remark"):
            value = sender.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(context.user_id or "?")
