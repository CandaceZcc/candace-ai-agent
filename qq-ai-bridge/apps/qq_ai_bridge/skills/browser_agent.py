"""Browser automation skill backed by the local pc-agent service."""

from __future__ import annotations

import re

from apps.qq_ai_bridge.adapters.napcat_client import send_group_msg, send_private_msg
from apps.qq_ai_bridge.services.browser_agent_service import run_browser_agent_task
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult


_URL_OR_DOMAIN_RE = re.compile(
    r"\b(https?://\S+|[a-z0-9][a-z0-9\-]*\.(?:com|cn|edu|edu\.cn|org|net|io|app|xyz)(?:/\S*)?)\b",
    re.IGNORECASE,
)

_BROWSER_INTENT_KEYWORDS = (
    "登录", "登入", "登陆",
    "帮我打开", "帮我上", "帮我在",
    "爬取", "抓取", "抓一下", "扒一下",
    "portal", "moodle", "ispace", "ddl",
    "remote-debug", "remote debug", "cdp", "端口转发",
)

class BrowserAgentSkill:
    """Route browser-intent requests to the local browser-agent service."""

    name = "browser_agent"

    def _looks_like_browser_intent(self, text: str) -> bool:
        """Return True if text reads like a web-automation request."""
        low = text.lower()
        if any(kw in low for kw in _BROWSER_INTENT_KEYWORDS):
            return True
        if _URL_OR_DOMAIN_RE.search(low):
            return True
        return False

    def match_reason(self, context: SkillContext) -> str:
        """Return human-readable match reason for debug logs."""
        text = context.normalized_msg.lower().strip()
        if not text:
            return "empty_text"

        explicit = text.startswith("browser ") or text.startswith("/browser ")
        implicit = self._looks_like_browser_intent(text)

        if not explicit and not implicit:
            return "missing_browser_prefix"

        kind = "explicit" if explicit else "implicit"

        if context.is_private:
            return f"{kind}_private_browser_command"

        if context.is_group:
            if not context.group_config.get("bot_can_reply", True):
                return "group_reply_disabled"
            if not explicit:
                return "group_not_triggered"
            reply_all_messages = context.group_config.get("reply_all_messages", False)
            if context.mentioned_self or reply_all_messages:
                return f"{kind}_group_browser_command"
            return "group_not_triggered"

        return "unsupported_message_type"

    def can_handle(self, context: SkillContext) -> bool:
        """Handle explicit browser-prefixed commands and private implicit requests."""
        reason = self.match_reason(context)
        return reason in {
            "explicit_private_browser_command",
            "explicit_group_browser_command",
            "implicit_private_browser_command",
            "implicit_group_browser_command",
        }

    def handle(self, context: SkillContext) -> SkillResult:
        """Run the local browser-agent task and relay its summary."""
        result = run_browser_agent_task(
            int(context.user_id or 0),
            context.effective_text,
            source_skill=self.name,
        )
        reply = str(result.get("reply") or "浏览器任务已处理。").strip()
        if context.is_private:
            send_private_msg(context.user_id, reply)
            return SkillResult(
                handled=True,
                source=self.name,
                response_payload={
                    "status": str(result.get("status") or "ok"),
                    "source": self.name,
                    "mode": "browser_agent",
                    "task": result.get("task"),
                },
            )
        if context.is_group:
            send_group_msg(context.group_id, reply, quiet=not context.should_log)
            return SkillResult(
                handled=True,
                source=self.name,
                response_payload={
                    "status": str(result.get("status") or "ok"),
                    "source": self.name,
                    "mode": "browser_agent",
                    "task": result.get("task"),
                },
            )
        return SkillResult(handled=False, source=self.name, status="ignore")
