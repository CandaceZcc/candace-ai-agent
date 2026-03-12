"""Chat skill for private and group text conversations."""

from __future__ import annotations

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text
from apps.qq_ai_bridge.adapters.napcat_client import send_group_msg
from apps.qq_ai_bridge.config.settings import ALLOWED_PRIVATE_USER
from apps.qq_ai_bridge.services.prompt_service import prepare_group_ai_prompt
from apps.qq_ai_bridge.services.private_chat_service import enqueue_private_text
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult
from shared.ai.llm_client import call_ai


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
        if not context.mentioned_self and not reply_all_messages:
            context.log("[ROUTE] 群聊未 @ 机器人，忽略")
            return SkillResult(handled=True, source=self.name, status="ignore")
        query = context.effective_text
        context.log(f"[ROUTE] effective_query={query!r}")
        if query == "":
            context.log("[ROUTE] 群聊无有效文本内容，忽略")
            return SkillResult(handled=True, source=self.name, status="ignore")
        context.log(f"[ROUTE] 群聊 query = {query!r}")

        prompt_payload = prepare_group_ai_prompt(context.group_id, query, user_id=context.user_id, log=context.log)
        context.log(
            "[GROUP_PROMPT]"
            f" mode={prompt_payload['prompt_mode']}"
            f" persona_chars={prompt_payload['persona_chars']}"
            f" history_chars={prompt_payload['history_chars']}"
            f" style_chars={prompt_payload['style_chars']}"
            f" current_message_chars={prompt_payload['current_message_chars']}"
            f" total_prompt_chars={prompt_payload['prompt_chars']}"
        )
        reply = call_ai(
            prompt_payload["prompt"],
            metadata={
                "user_id": f"group:{context.group_id}",
                "prompt_mode": prompt_payload["prompt_mode"],
                "query_len": prompt_payload["query_len"],
                "history_chars": prompt_payload["history_chars"],
                "history_items": prompt_payload["history_items"],
                "instruction_chars": prompt_payload["instruction_chars"],
                "prompt_chars": prompt_payload["prompt_chars"],
            },
        )
        send_group_msg(context.group_id, reply, quiet=not context.should_log)
        return SkillResult(handled=True, source=self.name, response_payload={"status": "ok", "source": self.name})
