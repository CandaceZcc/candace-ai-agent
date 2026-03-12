"""Chat skill for private and group text conversations."""

from __future__ import annotations

from apps.qq_ai_bridge.adapters.message_parser import has_meaningful_text, normalize_query_text
from apps.qq_ai_bridge.adapters.napcat_client import send_group_msg, send_private_msg
from apps.qq_ai_bridge.config.settings import ALLOWED_PRIVATE_USER, BASE_DATA_DIR
from apps.qq_ai_bridge.services.prompt_service import build_group_safe_prompt
from apps.qq_ai_bridge.services.private_chat_service import build_private_ai_prompt, get_user_workspace
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult
from shared.ai.llm_client import call_ai
from storage_utils import append_private_history, append_private_style_sample


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
            if not has_meaningful_text(context.data, context.self_id):
                context.log("[ROUTE] 私聊无有效文本内容，忽略")
                return SkillResult(handled=True, source=self.name, status="ignore")

            query = context.normalized_msg
            context.log(f"[ROUTE] 私聊 query = {query!r}")
            if query == "":
                context.log("[ROUTE] 私聊无有效文本内容，忽略")
                return SkillResult(handled=True, source=self.name, status="ignore")

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

            get_user_workspace(context.user_id)
            append_private_style_sample(BASE_DATA_DIR, context.user_id, ai_query, timestamp=context.timestamp)
            ai_input = build_private_ai_prompt(context.user_id, ai_query)
            reply = call_ai(ai_input)
            append_private_history(BASE_DATA_DIR, context.user_id, ai_query, reply, limit=20)
            send_private_msg(context.user_id, reply)
            return SkillResult(handled=True, source=self.name, response_payload={"status": "ok", "source": self.name})

        context.log("[ROUTE] 进入群聊分支")
        if not context.group_config.get("bot_can_reply", True):
            context.log("[ROUTE] 群配置禁止回复，忽略")
            return SkillResult(handled=True, source=self.name, status="ignore")

        reply_all_messages = context.group_config.get("reply_all_messages", False)
        if not context.mentioned_self and not reply_all_messages:
            context.log("[ROUTE] 群聊未 @ 机器人，忽略")
            return SkillResult(handled=True, source=self.name, status="ignore")
        if not has_meaningful_text(context.data, context.self_id):
            context.log("[ROUTE] 群聊无有效文本内容，忽略")
            return SkillResult(handled=True, source=self.name, status="ignore")

        query = context.normalized_msg
        context.log(f"[ROUTE] 群聊 query = {query!r}")
        if query == "":
            context.log("[ROUTE] 群聊无有效文本内容，忽略")
            return SkillResult(handled=True, source=self.name, status="ignore")

        safe_query = build_group_safe_prompt(context.group_id, query)
        reply = call_ai(safe_query)
        send_group_msg(context.group_id, reply, quiet=not context.should_log)
        return SkillResult(handled=True, source=self.name, response_payload={"status": "ok", "source": self.name})
