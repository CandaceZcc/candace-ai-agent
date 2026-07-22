"""Run credential-safe diagnostics for the read-only campus email agent."""

from __future__ import annotations

import argparse
import asyncio
import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import (
    BASE_DATA_DIR,
    EMAIL_ARCHIVE_RETENTION_DAYS,
    EMAIL_AUTOMATION_STATE_PATH,
    EMAIL_IMAP_HOST,
    EMAIL_IMAP_MAILBOX,
    EMAIL_IMAP_PASSWORD,
    EMAIL_IMAP_PORT,
    EMAIL_IMAP_TIMEOUT_SECONDS,
    EMAIL_IMAP_USERNAME,
    EMAIL_MAX_BODY_CHARS,
    EMAIL_MAX_MESSAGES_PER_RUN,
    EMAIL_MAX_TOTAL_CHARS,
    OWNER_QQ,
    email_config_summary,
)
from apps.qq_ai_bridge.services.email_archive_service import EmailArchiveService
from apps.qq_ai_bridge.services.email_automation_service import (
    EmailAutomationService,
    route_classification,
)
from apps.qq_ai_bridge.services.email_imap_service import EmailImapError, EmailImapService
from apps.qq_ai_bridge.services.email_models import (
    EmailEnvelope,
    EmailFetchedMessage,
    EmailUidBatch,
)
from apps.qq_ai_bridge.services.email_preference_service import EmailPreferenceStore
from apps.qq_ai_bridge.services.email_processing_store import EmailProcessingStore
from apps.qq_ai_bridge.services.email_rule_classifier import EmailRuleClassifier
from apps.qq_ai_bridge.services.email_semantic_classifier import EmailSemanticClassifier
from apps.qq_ai_bridge.services.time_utils import get_now_local
from shared.ai.agent_runtime import AgentRuntime

_SIMULATION_UID_VALIDITY = "candace-simulation-v1"
_SIMULATION_MAILBOX = "SIMULATION"
_SIMULATION_NOTICE = "【邮件自动推送模拟】\n这是一条合成邮件演练消息，请勿按其中内容行动。\n"


class _SyntheticImapService:
    def __init__(self, messages: tuple[EmailFetchedMessage, ...]) -> None:
        self._messages = messages

    def fetch_new(self, *, last_uid: int, limit: int) -> EmailUidBatch:
        selected = tuple(message for message in self._messages if message.uid > last_uid)
        return EmailUidBatch(_SIMULATION_UID_VALIDITY, selected[: max(0, int(limit))])


class _SimulationSender:
    def __init__(
        self,
        *,
        deliver_to_owner: bool,
        send_private: Callable[..., Any],
    ) -> None:
        self.deliver_to_owner = bool(deliver_to_owner)
        self._send_private = send_private
        self.attempts: list[str] = []

    def __call__(self, user_id: int, text: str, **kwargs: Any) -> Any:
        self.attempts.append(_simulation_message_kind(text))
        if not self.deliver_to_owner:
            return {"ok": True}
        return self._send_private(user_id, _SIMULATION_NOTICE + text, **kwargs)

    def counts(self) -> dict[str, int]:
        return {
            "digest": self.attempts.count("digest"),
            "immediate": self.attempts.count("immediate"),
            "total": len(self.attempts),
        }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    checks = parser.add_mutually_exclusive_group(required=True)
    checks.add_argument("--config", action="store_true", help="Print redacted configuration")
    checks.add_argument("--imap", action="store_true", help="Run a one-message read-only UID check")
    checks.add_argument("--shadow-report", action="store_true", help="Print private state counts")
    checks.add_argument("--cleanup", action="store_true", help="Clean expired private archives")
    checks.add_argument(
        "--simulate-automation",
        action="store_true",
        help="Run an isolated synthetic classification and delivery rehearsal",
    )
    checks.add_argument(
        "--bootstrap-cursor",
        action="store_true",
        help="Set the production cursor to the current read-only mailbox snapshot",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report cleanup matches only")
    parser.add_argument(
        "--deliver-to-owner",
        action="store_true",
        help="Send distilled simulation output to the configured owner QQ",
    )
    parser.add_argument(
        "--accept-qq-send",
        action="store_true",
        help="Explicitly accept the real QQ sends requested by --deliver-to-owner",
    )
    parser.add_argument(
        "--accept-skip-existing",
        action="store_true",
        help="Explicitly accept treating existing mailbox messages as already seen",
    )
    args = parser.parse_args(argv)
    if args.dry_run and not args.cleanup:
        parser.error("--dry-run requires --cleanup")
    if (args.deliver_to_owner or args.accept_qq_send) and not args.simulate_automation:
        parser.error("QQ simulation delivery flags require --simulate-automation")
    if args.deliver_to_owner != args.accept_qq_send:
        parser.error("--deliver-to-owner and --accept-qq-send must be used together")
    if args.accept_skip_existing and not args.bootstrap_cursor:
        parser.error("--accept-skip-existing requires --bootstrap-cursor")
    if args.bootstrap_cursor and not args.accept_skip_existing:
        parser.error("--bootstrap-cursor requires --accept-skip-existing")

    try:
        if args.config:
            return _emit(
                {
                    "check": "config",
                    "config": email_config_summary(),
                    "identity": _mask_identity(EMAIL_IMAP_USERNAME),
                    "ok": True,
                }
            )
        if args.imap:
            batch = _build_imap_service().fetch_new(last_uid=0, limit=1)
            return _emit(
                {
                    "check": "imap",
                    "message_count": len(batch.messages),
                    "ok": True,
                    "uidvalidity": batch.uid_validity,
                }
            )
        if args.shadow_report:
            store = _build_processing_store()
            now = get_now_local()
            return _emit(
                {
                    "check": "shadow_report",
                    "ok": True,
                    "pending_analysis": len(store.pending_analysis(limit=100)),
                    "pending_digest_24h": len(store.pending_digest(now, lookback_hours=24)),
                }
            )
        if args.simulate_automation:
            report = asyncio.run(
                _run_automation_simulation(deliver_to_owner=args.deliver_to_owner)
            )
            return _emit(report, exit_code=0 if report.get("ok") is True else 1)
        if args.bootstrap_cursor:
            return _emit(_bootstrap_automation_cursor())
        matches = _build_archive_service().cleanup_expired(
            retention_days=EMAIL_ARCHIVE_RETENTION_DAYS,
            dry_run=args.dry_run,
        )
        return _emit(
            {
                "check": "cleanup",
                "deleted_count": 0 if args.dry_run else len(matches),
                "dry_run": args.dry_run,
                "matched_count": len(matches),
                "ok": True,
            }
        )
    except EmailImapError as exc:
        check = "cursor_bootstrap" if args.bootstrap_cursor else "imap"
        return _emit({"check": check, "error": exc.code, "ok": False}, exit_code=1)
    except Exception as exc:
        check = "email_agent"
        if args.simulate_automation:
            check = "automation_simulation"
        elif args.bootstrap_cursor:
            check = "cursor_bootstrap"
        return _emit(
            {
                "check": check,
                "error": type(exc).__name__,
                "ok": False,
            },
            exit_code=1,
        )


def _bootstrap_automation_cursor() -> dict[str, Any]:
    snapshot = _build_imap_service().snapshot_cursor()
    store = _build_processing_store()
    current = store.cursor(EMAIL_IMAP_MAILBOX)
    had_existing_cursor = bool(current.uid_validity or current.last_uid)
    latest_uid = snapshot.latest_uid
    if current.uid_validity == snapshot.uid_validity:
        latest_uid = max(current.last_uid, latest_uid)
    store.set_cursor(EMAIL_IMAP_MAILBOX, snapshot.uid_validity, latest_uid)
    return {
        "check": "cursor_bootstrap",
        "cursor_initialized": True,
        "mailbox_had_existing_cursor": had_existing_cursor,
        "ok": True,
    }


async def _run_automation_simulation(
    *,
    deliver_to_owner: bool,
    semantic_classifier: Any | None = None,
    send_private: Callable[..., Any] = send_private_msg,
) -> dict[str, Any]:
    now = get_now_local()
    scenarios = _synthetic_scenarios(now)
    fetched = tuple(
        EmailFetchedMessage(uid=index, envelope=envelope)
        for index, (_, _, envelope) in enumerate(scenarios, start=1)
    )
    sender = _SimulationSender(
        deliver_to_owner=deliver_to_owner,
        send_private=send_private,
    )

    with tempfile.TemporaryDirectory(prefix="candace-email-simulation-") as temp_dir:
        root = Path(temp_dir)
        store = EmailProcessingStore(root / "automation-state.json", now=lambda: now)
        service = EmailAutomationService(
            imap_service=_SyntheticImapService(fetched),
            archive_service=EmailArchiveService(root / "email", now=lambda: now),
            preference_store=EmailPreferenceStore(
                root / "profile.json",
                root / "learned-feedback.json",
            ),
            rule_classifier=EmailRuleClassifier(
                owner_address="owner@example.invalid",
                max_body_chars=EMAIL_MAX_BODY_CHARS,
            ),
            semantic_classifier=semantic_classifier or EmailSemanticClassifier(
                runtime=AgentRuntime(legacy_call=None),
                max_body_chars=EMAIL_MAX_BODY_CHARS,
                max_total_chars=EMAIL_MAX_TOTAL_CHARS,
            ),
            processing_store=store,
            send_private=sender,
            owner_qq=OWNER_QQ,
            mailbox=_SIMULATION_MAILBOX,
            monitor_enabled=True,
            immediate_push_enabled=True,
            digest_push_enabled=True,
            shadow_mode=False,
            max_messages=max(3, EMAIL_MAX_MESSAGES_PER_RUN),
        )

        await service.poll(now)
        sends_after_first_poll = len(sender.attempts)
        await service.poll(now + timedelta(minutes=5))
        poll_is_idempotent = len(sender.attempts) == sends_after_first_poll

        await service.run_digest(now, "20:30")
        sends_after_first_digest = len(sender.attempts)
        await service.run_digest(now, "20:30")
        digest_is_idempotent = len(sender.attempts) == sends_after_first_digest

        scenario_reports = []
        for index, (name, expected_route, _envelope) in enumerate(scenarios):
            record = store.find_by_alias(f"E-{1000 + index}")
            if record is None:
                raise RuntimeError("synthetic scenario record missing")
            scenario_reports.append(
                {
                    "alias": record.alias,
                    "delivery_state": record.delivery_state,
                    "expected_route": expected_route,
                    "name": name,
                    "relevance": (
                        record.classification.relevance_score
                        if record.classification is not None
                        else None
                    ),
                    "route": route_classification(
                        record.classification,
                        record.rule_decision,
                    ),
                    "urgency": (
                        record.classification.urgency
                        if record.classification is not None
                        else None
                    ),
                }
            )

    counts = sender.counts()
    routes_match = all(
        item["route"] == item["expected_route"] for item in scenario_reports
    )
    states_match = tuple(item["delivery_state"] for item in scenario_reports) == (
        "immediate_sent",
        "digest_sent",
        "ignored",
    )
    send_counts_match = counts == {"digest": 1, "immediate": 1, "total": 2}
    return {
        "check": "automation_simulation",
        "delivered_to_owner": bool(deliver_to_owner),
        "idempotency": {
            "digest": digest_is_idempotent,
            "poll": poll_is_idempotent,
        },
        "ok": bool(
            routes_match
            and states_match
            and send_counts_match
            and poll_is_idempotent
            and digest_is_idempotent
        ),
        "scenarios": scenario_reports,
        "send_counts": counts,
    }


def _synthetic_scenarios(now: datetime) -> tuple[tuple[str, str, EmailEnvelope], ...]:
    urgent_deadline = (now + timedelta(hours=2)).isoformat()
    return (
        (
            "urgent_course_change",
            "immediate",
            EmailEnvelope(
                message_id="<candace-sim-urgent@example.invalid>",
                subject="CST3001 Final Examination Time Changed - Year 3 Action Required",
                sender="CST Course Instructor <course-instructor@example.invalid>",
                recipients=("owner@example.invalid",),
                sent_at=now - timedelta(minutes=10),
                body_text=(
                    "This is an official Year 3 CST course change. The CST3001 final exam "
                    f"time changed today. Please confirm the new arrangement by {urgent_deadline}."
                ),
                attachments=(),
            ),
        ),
        (
            "robotics_competition",
            "digest",
            EmailEnvelope(
                message_id="<candace-sim-robotics@example.invalid>",
                subject="Robotics and Embedded Systems Competition Information for CST Students",
                sender="Robotics Lab <robotics-lab@example.invalid>",
                recipients=("owner@example.invalid",),
                sent_at=now - timedelta(minutes=30),
                body_text=(
                    "Information for computer science students interested in robotics, embedded "
                    "systems, firmware and IoT. This is not urgent and no action is required now."
                ),
                attachments=(),
            ),
        ),
        (
            "unrelated_recruitment",
            "ignore",
            EmailEnvelope(
                message_id="<candace-sim-recruitment@example.invalid>",
                subject="General Campus Recruitment and Career Fair",
                sender="Career Mailing List <careers@example.invalid>",
                recipients=("all-students@example.invalid",),
                sent_at=now - timedelta(minutes=50),
                body_text=(
                    "Campus recruitment and career fair mailing list announcement for all "
                    "students. This generic recruitment notice is unrelated to your studies."
                ),
                attachments=(),
            ),
        ),
    )


def _simulation_message_kind(text: str) -> str:
    if str(text).startswith("【重要邮件"):
        return "immediate"
    if str(text).startswith("【最近 24 小时邮件摘要】"):
        return "digest"
    return "unknown"


def _build_imap_service() -> EmailImapService:
    return EmailImapService(
        host=EMAIL_IMAP_HOST,
        port=EMAIL_IMAP_PORT,
        username=EMAIL_IMAP_USERNAME,
        password=EMAIL_IMAP_PASSWORD,
        mailbox=EMAIL_IMAP_MAILBOX,
        timeout_seconds=EMAIL_IMAP_TIMEOUT_SECONDS,
        max_body_chars=EMAIL_MAX_BODY_CHARS,
    )


def _build_processing_store() -> EmailProcessingStore:
    return EmailProcessingStore(EMAIL_AUTOMATION_STATE_PATH)


def _build_archive_service() -> EmailArchiveService:
    return EmailArchiveService(Path(BASE_DATA_DIR) / "email")


def _mask_identity(value: str) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        return "missing"
    local = normalized.split("@", 1)[0]
    return f"{local[:1] or '*'}***@***" if "@" in normalized else f"{local[:1]}***"


def _emit(payload: dict[str, Any], *, exit_code: int = 0) -> int:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
