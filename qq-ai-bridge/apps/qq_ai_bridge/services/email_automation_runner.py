"""Independent background runner for personalized email automation."""

from __future__ import annotations

import asyncio
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from shared.ai.agent_runtime import AgentRuntime

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import (
    BASE_DATA_DIR,
    EMAIL_AUTOMATION_STATE_PATH,
    EMAIL_DIGEST_PUSH_ENABLED,
    EMAIL_DIGEST_TIMES,
    EMAIL_FEEDBACK_PATH,
    EMAIL_IMAP_HOST,
    EMAIL_IMAP_MAILBOX,
    EMAIL_IMAP_PASSWORD,
    EMAIL_IMAP_PORT,
    EMAIL_IMAP_TIMEOUT_SECONDS,
    EMAIL_IMAP_USERNAME,
    EMAIL_IMMEDIATE_PUSH_ENABLED,
    EMAIL_MAX_BODY_CHARS,
    EMAIL_MAX_MESSAGES_PER_RUN,
    EMAIL_MAX_TOTAL_CHARS,
    EMAIL_MONITOR_ENABLED,
    EMAIL_POLL_INTERVAL_SECONDS,
    EMAIL_PROFILE_PATH,
    EMAIL_SHADOW_MODE,
    OWNER_QQ,
)
from apps.qq_ai_bridge.logging.bridge_log import log_warn
from apps.qq_ai_bridge.services.email_archive_service import EmailArchiveService
from apps.qq_ai_bridge.services.email_automation_service import EmailAutomationService
from apps.qq_ai_bridge.services.email_imap_service import EmailImapService
from apps.qq_ai_bridge.services.email_preference_service import EmailPreferenceStore
from apps.qq_ai_bridge.services.email_processing_store import EmailProcessingStore
from apps.qq_ai_bridge.services.email_rule_classifier import EmailRuleClassifier
from apps.qq_ai_bridge.services.email_semantic_classifier import EmailSemanticClassifier
from apps.qq_ai_bridge.services.time_utils import get_now_local


class EmailAutomationRunner:
    def __init__(
        self,
        *,
        service_factory: Callable[[], Any],
        monitor_enabled: bool,
        digest_enabled: bool,
        poll_interval_seconds: int,
        digest_times: tuple[str, ...],
        now: Callable[[], datetime] = get_now_local,
        sleep: Callable[[float], None] = time.sleep,
        run_async: Callable[[Any], Any] = asyncio.run,
    ) -> None:
        self._service_factory = service_factory
        self._monitor_enabled = bool(monitor_enabled)
        self._digest_enabled = bool(digest_enabled)
        self._poll_interval_seconds = max(1, int(poll_interval_seconds))
        self._digest_times = tuple(digest_times)
        self._now = now
        self._sleep = sleep
        self._run_async = run_async

    def run_forever(self) -> None:
        service = None
        while True:
            if service is None:
                try:
                    service = self._service_factory()
                except Exception as exc:
                    log_warn(
                        "EMAIL_AUTOMATION",
                        "service setup failed type=%s",
                        type(exc).__name__,
                    )
                    self._sleep(self._poll_interval_seconds)
                    continue
            self.run_once(service, self._now())
            self._sleep(self._poll_interval_seconds)

    def run_once(self, service: Any, now: datetime) -> None:
        if self._monitor_enabled:
            try:
                self._run_async(service.poll(now))
            except Exception as exc:
                log_warn("EMAIL_AUTOMATION", "poll failed type=%s", type(exc).__name__)
        if not self._digest_enabled:
            return
        for slot in _due_digest_slots(now, self._digest_times):
            try:
                self._run_async(service.run_digest(now, slot))
            except Exception as exc:
                log_warn("EMAIL_AUTOMATION", "digest failed type=%s", type(exc).__name__)


def start_email_automation(
    *,
    monitor_enabled: bool = EMAIL_MONITOR_ENABLED,
    digest_enabled: bool = EMAIL_DIGEST_PUSH_ENABLED,
    thread_factory: Callable[..., Any] = threading.Thread,
    runner_factory: Callable[[], EmailAutomationRunner] | None = None,
) -> Any | None:
    if not monitor_enabled and not digest_enabled:
        return None
    runner = (runner_factory or _build_default_runner)()
    worker = thread_factory(target=runner.run_forever, name="email-automation", daemon=True)
    worker.start()
    return worker


def _build_default_runner() -> EmailAutomationRunner:
    return EmailAutomationRunner(
        service_factory=_build_default_service,
        monitor_enabled=EMAIL_MONITOR_ENABLED,
        digest_enabled=EMAIL_DIGEST_PUSH_ENABLED,
        poll_interval_seconds=EMAIL_POLL_INTERVAL_SECONDS,
        digest_times=EMAIL_DIGEST_TIMES,
    )


def _build_default_service() -> EmailAutomationService:
    archive = EmailArchiveService(Path(BASE_DATA_DIR) / "email")
    processing = EmailProcessingStore(EMAIL_AUTOMATION_STATE_PATH)
    preferences = EmailPreferenceStore(EMAIL_PROFILE_PATH, EMAIL_FEEDBACK_PATH)
    imap = EmailImapService(
        host=EMAIL_IMAP_HOST,
        port=EMAIL_IMAP_PORT,
        username=EMAIL_IMAP_USERNAME,
        password=EMAIL_IMAP_PASSWORD,
        mailbox=EMAIL_IMAP_MAILBOX,
        timeout_seconds=EMAIL_IMAP_TIMEOUT_SECONDS,
        max_body_chars=EMAIL_MAX_BODY_CHARS,
    )
    semantic = EmailSemanticClassifier(
        runtime=AgentRuntime(legacy_call=None),
        max_body_chars=EMAIL_MAX_BODY_CHARS,
        max_total_chars=EMAIL_MAX_TOTAL_CHARS,
    )
    return EmailAutomationService(
        imap_service=imap,
        archive_service=archive,
        preference_store=preferences,
        rule_classifier=EmailRuleClassifier(
            owner_address=EMAIL_IMAP_USERNAME,
            max_body_chars=EMAIL_MAX_BODY_CHARS,
        ),
        semantic_classifier=semantic,
        processing_store=processing,
        send_private=send_private_msg,
        owner_qq=OWNER_QQ,
        mailbox=EMAIL_IMAP_MAILBOX,
        monitor_enabled=EMAIL_MONITOR_ENABLED,
        immediate_push_enabled=EMAIL_IMMEDIATE_PUSH_ENABLED,
        digest_push_enabled=EMAIL_DIGEST_PUSH_ENABLED,
        shadow_mode=EMAIL_SHADOW_MODE,
        max_messages=EMAIL_MAX_MESSAGES_PER_RUN,
    )


def _due_digest_slots(now: datetime, digest_times: tuple[str, ...]) -> tuple[datetime, ...]:
    candidates = []
    for day in (now.date() - timedelta(days=1), now.date()):
        for value in digest_times:
            hour_text, minute_text = value.split(":", 1)
            scheduled = now.replace(
                year=day.year,
                month=day.month,
                day=day.day,
                hour=int(hour_text),
                minute=int(minute_text),
                second=0,
                microsecond=0,
            )
            age = now - scheduled
            if timedelta(0) <= age <= timedelta(hours=24):
                candidates.append(scheduled)
    return tuple(sorted(candidates))


__all__ = ["EmailAutomationRunner", "start_email_automation"]
