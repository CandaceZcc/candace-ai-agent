"""Placeholder skill for future browser automation tasks."""

from __future__ import annotations

import re

from apps.qq_ai_bridge.adapters.napcat_client import send_group_msg, send_private_msg
from apps.qq_ai_bridge.services.browser_agent_service import build_browser_agent_request
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

_PLACEHOLDER_MSG = (
    "浏览器自动化当前还没有接入 QQ 侧：BrowserAgentSkill 还是占位状态，\n"
    "pc-agent 的 Playwright runtime 也没暴露给 bridge 调用。\n"
    "不要按我（或 chat）之前的建议去开 Chrome 远程调试端口或做 SSH 转发——那条路径根本没有实现。\n\n"
    "变通办法：\n"
    "1. 你自己登录目标页面，把内容复制或截图发给我，我来整理\n"
    "2. 如果要做批量抓取 portal/DDL，直接运行 ~/.openclaw/workspace/crawl_assignments.js\n"
    "3. 等 browser_agent 接通 Playwright 后再说（优先级在 VoCat 之后）"
)


class BrowserAgentSkill:
    """Reserved placeholder for future browser-agent integration.

    Now also matches on URL / browser-intent keywords so that users who naturally
    say "帮我登录 portal.xxx 找 ddl" get an honest placeholder reply instead of
    falling through to chat, which tends to hallucinate SSH/CDP workarounds.
    """

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
        """Return an honest placeholder response instead of falling through to chat."""
        _ = build_browser_agent_request("open_url", {"url": "about:blank"})
        if context.is_private:
            send_private_msg(context.user_id, _PLACEHOLDER_MSG)
            return SkillResult(
                handled=True,
                source=self.name,
                response_payload={"status": "ok", "source": self.name, "mode": "placeholder"},
            )
        if context.is_group:
            send_group_msg(context.group_id, _PLACEHOLDER_MSG, quiet=not context.should_log)
            return SkillResult(
                handled=True,
                source=self.name,
                response_payload={"status": "ok", "source": self.name, "mode": "placeholder"},
            )
        return SkillResult(handled=False, source=self.name, status="ignore")
