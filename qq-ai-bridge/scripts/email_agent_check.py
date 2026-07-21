"""Run credential-safe diagnostics for the read-only campus email agent."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

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
    email_config_summary,
)
from apps.qq_ai_bridge.services.email_archive_service import EmailArchiveService
from apps.qq_ai_bridge.services.email_imap_service import EmailImapError, EmailImapService
from apps.qq_ai_bridge.services.email_processing_store import EmailProcessingStore
from apps.qq_ai_bridge.services.time_utils import get_now_local


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    checks = parser.add_mutually_exclusive_group(required=True)
    checks.add_argument("--config", action="store_true", help="Print redacted configuration")
    checks.add_argument("--imap", action="store_true", help="Run a one-message read-only UID check")
    checks.add_argument("--shadow-report", action="store_true", help="Print private state counts")
    checks.add_argument("--cleanup", action="store_true", help="Clean expired private archives")
    parser.add_argument("--dry-run", action="store_true", help="Report cleanup matches only")
    args = parser.parse_args(argv)
    if args.dry_run and not args.cleanup:
        parser.error("--dry-run requires --cleanup")

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
        return _emit({"check": "imap", "error": exc.code, "ok": False}, exit_code=1)
    except Exception as exc:
        return _emit(
            {"check": "email_agent", "error": type(exc).__name__, "ok": False},
            exit_code=1,
        )


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
