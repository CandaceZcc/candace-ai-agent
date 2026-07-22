"""Owner-private QQ commands for read-only campus email digests."""

from __future__ import annotations

import threading
from datetime import datetime
from email.utils import parseaddr
from pathlib import Path
from typing import Any, Callable

from shared.ai.agent_runtime import AgentRuntime

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import (
    AGENT_PROVIDER,
    BASE_DATA_DIR,
    CHAT_COMPATIBLE_MODEL,
    EMAIL_AGENT_ENABLED,
    EMAIL_AUTOMATION_STATE_PATH,
    EMAIL_FEEDBACK_PATH,
    EMAIL_IMAP_HOST,
    EMAIL_IMAP_MAILBOX,
    EMAIL_IMAP_PASSWORD,
    EMAIL_IMAP_PORT,
    EMAIL_IMAP_TIMEOUT_SECONDS,
    EMAIL_IMAP_USERNAME,
    EMAIL_MAX_BODY_CHARS,
    EMAIL_MAX_MESSAGES_PER_RUN,
    EMAIL_MAX_RANGE_DAYS,
    EMAIL_MAX_TOTAL_CHARS,
    EMAIL_PROFILE_PATH,
    EMAIL_SUMMARY_MODEL,
    OPENAI_AGENT_MODEL,
    OWNER_QQ,
    RESPONSES_PROXY_MODEL,
)
from apps.qq_ai_bridge.logging.bridge_log import log_warn
from apps.qq_ai_bridge.services.email_archive_service import EmailArchiveService
from apps.qq_ai_bridge.services.email_digest_service import EmailDigestError, EmailDigestService
from apps.qq_ai_bridge.services.email_imap_service import EmailImapError, EmailImapService
from apps.qq_ai_bridge.services.email_models import EmailCommand
from apps.qq_ai_bridge.services.email_preference_service import EmailPreferenceStore
from apps.qq_ai_bridge.services.email_processing_store import EmailProcessingStore
from apps.qq_ai_bridge.services.email_query_service import parse_email_command
from apps.qq_ai_bridge.services.private_chat_service import run_agent_runtime_sync
from apps.qq_ai_bridge.services.runtime_resources import submit_chat_task
from apps.qq_ai_bridge.services.time_utils import get_now_local
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult

_EMAIL_HELP = """邮件命令：
- 邮件 今天
- 邮件 昨天
- 邮件 本周
- 邮件 上周
- 邮件 最近 N 天
- 邮件 E-1042 有用/忽略/忽略此类/关注发件人/撤销反馈
- 邮件 偏好
- 邮件 状态
- 邮件 帮助"""
_EMAIL_QUEUED = "正在读取并整理邮件，完成后会发给你。"
_EMAIL_BUSY = "当前邮件任务较多，请稍后再试。"


class EmailSkill:
    name = "email"

    def __init__(
        self,
        *,
        enabled: bool = EMAIL_AGENT_ENABLED,
        owner_qq: int = OWNER_QQ,
        submit_task: Callable[..., Any] = submit_chat_task,
        digest_service_factory: Callable[[], Any] | None = None,
        send_private: Callable[..., dict] = send_private_msg,
        run_async: Callable[[Any], Any] = run_agent_runtime_sync,
        provider_name: str = AGENT_PROVIDER,
        model_name: str | None = None,
        now: Callable[[], datetime] = get_now_local,
        processing_store: Any | None = None,
        preference_store: Any | None = None,
        archive_service: Any | None = None,
    ) -> None:
        self._enabled = bool(enabled)
        self._owner_qq = int(owner_qq or 0)
        self._submit_task = submit_task
        self._digest_service_factory = digest_service_factory or _build_default_digest_service
        self._send_private = send_private
        self._run_async = run_async
        self._provider_name = str(provider_name or "")
        self._model_name = str(model_name or _configured_summary_model())
        self._now = now
        self._processing_store = processing_store
        self._preference_store = preference_store
        self._archive_service = archive_service
        self._state_lock = threading.Lock()
        self._last_success_at: datetime | None = None

    def match_reason(self, context: SkillContext) -> str:
        if not self._enabled:
            return "email_disabled"
        if not context.is_private:
            return "not_private"
        if int(context.user_id or 0) != self._owner_qq:
            return "not_owner"
        command = self._parse(context.effective_text)
        return f"email_{command.kind}" if command.kind != "no_match" else "not_email_command"

    def can_handle(self, context: SkillContext) -> bool:
        if (
            not self._enabled
            or not context.is_private
            or int(context.user_id or 0) != self._owner_qq
        ):
            return False
        return self._parse(context.effective_text).kind != "no_match"

    def handle(self, context: SkillContext) -> SkillResult:
        if not self.can_handle(context):
            return SkillResult(handled=False, source=self.name, status="ignore")
        command = self._parse(context.effective_text)
        if command.kind == "help":
            return self._text_result("help", _EMAIL_HELP)
        if command.kind == "status":
            return self._text_result("status", self._status_text())
        if command.kind == "preferences":
            return self._text_result("preferences", self._preferences().summary())
        if command.kind == "feedback":
            return self._handle_feedback(command)
        if command.kind == "invalid" or command.query is None:
            return self._text_result("invalid", _EMAIL_HELP)

        future = self._submit_task(self._run_worker, int(context.user_id or 0), command)
        if future is None:
            return self._text_result("busy", _EMAIL_BUSY)
        return SkillResult(
            handled=True,
            source=self.name,
            status="queued",
            response_text=_EMAIL_QUEUED,
            response_payload={"status": "queued"},
            already_sent=False,
        )

    def _parse(self, text: str) -> EmailCommand:
        return parse_email_command(
            text,
            now=self._now(),
            max_range_days=EMAIL_MAX_RANGE_DAYS,
            limit=EMAIL_MAX_MESSAGES_PER_RUN,
        )

    def _run_worker(self, user_id: int, command: EmailCommand) -> None:
        try:
            service = self._digest_service_factory()
            digest = self._run_async(
                service.build_digest(command.query, period_label=command.period_label)
            )
            send_result = self._send_private(
                user_id,
                digest.summary_text,
                quiet=True,
                redact_content=True,
            )
            if send_result.get("ok"):
                with self._state_lock:
                    self._last_success_at = self._now()
            return
        except EmailImapError as exc:
            code = exc.code
            message = _imap_error_message(code)
        except EmailDigestError as exc:
            code = exc.code
            message = "邮件摘要生成失败，稍后再试。"
        except Exception as exc:
            code = type(exc).__name__
            message = "邮件摘要生成失败，稍后再试。"
        log_warn("EMAIL", "worker failed code=%s", code)
        self._send_private(user_id, message, quiet=True, redact_content=True)

    def _handle_feedback(self, command: EmailCommand) -> SkillResult:
        record = self._processing().find_by_alias(command.alias)
        if record is None:
            return self._text_result(
                "feedback_not_found",
                f"未找到邮件编号 {command.alias}，可能已过期。",
            )
        if command.feedback_action == "undo":
            removed = self._preferences().undo_feedback(command.alias)
            text = (
                f"已撤销 {command.alias} 的反馈。"
                if removed
                else f"{command.alias} 没有可撤销的反馈。"
            )
            return self._text_result("feedback", text)

        signals = self._feedback_signals(record, command.feedback_action)
        if command.feedback_action == "watch_sender" and "sender" not in signals:
            return self._text_result(
                "feedback_archive_expired",
                f"{command.alias} 的私有归档已过期，无法关注发件人。",
            )
        self._preferences().apply_feedback(
            command.alias,
            command.feedback_action,
            signals,
        )
        action_label = {
            "useful": "有用",
            "ignore": "忽略",
            "ignore_similar": "忽略此类",
            "watch_sender": "关注发件人",
        }[command.feedback_action]
        return self._text_result(
            "feedback",
            f"已记录 {command.alias}：{action_label}。可用“邮件 {command.alias} 撤销反馈”撤销。",
        )

    def _feedback_signals(self, record: Any, action: str) -> dict[str, str]:
        classification = getattr(record, "classification", None)
        category = str(getattr(classification, "category", "") or "").strip().lower()
        if action == "ignore_similar":
            return {"category": category} if category else {}

        envelope = self._archive().load_envelope(record.message_hash)
        sender = parseaddr(str(getattr(envelope, "sender", "") or ""))[1].strip().lower()
        if action == "watch_sender":
            return {"sender": sender} if sender else {}
        signals = {}
        if sender:
            signals["sender"] = sender
        if category:
            signals["category"] = category
        return signals

    def _processing(self) -> Any:
        if self._processing_store is None:
            self._processing_store = EmailProcessingStore(EMAIL_AUTOMATION_STATE_PATH)
        return self._processing_store

    def _preferences(self) -> Any:
        if self._preference_store is None:
            self._preference_store = EmailPreferenceStore(EMAIL_PROFILE_PATH, EMAIL_FEEDBACK_PATH)
        return self._preference_store

    def _archive(self) -> Any:
        if self._archive_service is None:
            self._archive_service = EmailArchiveService(Path(BASE_DATA_DIR) / "email")
        return self._archive_service

    def _status_text(self) -> str:
        with self._state_lock:
            last_success = self._last_success_at
        success_text = (
            last_success.astimezone().strftime("%Y-%m-%d %H:%M:%S")
            if last_success is not None and last_success.tzinfo is not None
            else last_success.strftime("%Y-%m-%d %H:%M:%S")
            if last_success is not None
            else "暂无"
        )
        return (
            "邮件摘要状态：已启用\n"
            f"Provider：{self._provider_name}\n"
            f"Model：{self._model_name}\n"
            f"最近成功：{success_text}"
        )

    def _text_result(self, status: str, text: str) -> SkillResult:
        return SkillResult(
            handled=True,
            source=self.name,
            status=status,
            response_text=text,
            already_sent=False,
        )


def _build_default_digest_service() -> EmailDigestService:
    imap_service = EmailImapService(
        host=EMAIL_IMAP_HOST,
        port=EMAIL_IMAP_PORT,
        username=EMAIL_IMAP_USERNAME,
        password=EMAIL_IMAP_PASSWORD,
        mailbox=EMAIL_IMAP_MAILBOX,
        timeout_seconds=EMAIL_IMAP_TIMEOUT_SECONDS,
        max_body_chars=EMAIL_MAX_BODY_CHARS,
    )
    archive_service = EmailArchiveService(Path(BASE_DATA_DIR) / "email")
    return EmailDigestService(
        imap_service=imap_service,
        archive_service=archive_service,
        runtime=AgentRuntime(legacy_call=None),
        model_name=_configured_summary_model(),
        max_messages=EMAIL_MAX_MESSAGES_PER_RUN,
        max_body_chars=EMAIL_MAX_BODY_CHARS,
        max_total_chars=EMAIL_MAX_TOTAL_CHARS,
    )


def _configured_summary_model() -> str:
    if EMAIL_SUMMARY_MODEL:
        return EMAIL_SUMMARY_MODEL
    return {
        "openai": OPENAI_AGENT_MODEL,
        "responses_proxy": RESPONSES_PROXY_MODEL,
        "chat_compatible": CHAT_COMPATIBLE_MODEL,
    }.get(AGENT_PROVIDER, "")


def _imap_error_message(code: str) -> str:
    if code == "email_config_error":
        return "邮件功能还没配置好。"
    if code == "email_auth_error":
        return "邮箱登录失败，请检查客户端专用密码。"
    if code == "email_network_error":
        return "邮箱连接失败，稍后再试。"
    return "邮件读取失败，稍后再试。"


__all__ = ["EmailSkill"]
