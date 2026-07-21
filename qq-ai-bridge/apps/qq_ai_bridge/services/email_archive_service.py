"""Private atomic archive and digest cache for normalized email data."""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Callable

from apps.qq_ai_bridge.services.email_models import (
    EmailAttachment,
    EmailDigest,
    EmailEnvelope,
    EmailQuery,
)
from apps.qq_ai_bridge.services.time_utils import LOCAL_TIMEZONE

_SCHEMA_VERSION = 1


class EmailArchiveService:
    def __init__(
        self,
        email_data_root: str | Path,
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.root = Path(email_data_root).expanduser().resolve()
        self._now = now or (lambda: datetime.now(timezone.utc))

    def archive_envelope(self, envelope: EmailEnvelope) -> Path:
        sent_date = _envelope_date(envelope, fallback=self._now())
        message_hash = hashlib.sha256(envelope.message_id.encode("utf-8")).hexdigest()
        path = self.root / "archive" / sent_date.isoformat() / f"{message_hash}.json"
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "message": _serialize_envelope(envelope),
        }
        if _json_file_equals(path, payload):
            return path
        _atomic_write_json(path, payload)
        return path

    def load_envelope(self, message_hash: str) -> EmailEnvelope | None:
        normalized_hash = str(message_hash or "").strip().lower()
        if len(normalized_hash) != 64 or any(
            character not in "0123456789abcdef" for character in normalized_hash
        ):
            return None
        archive_root = self.root / "archive"
        for path in sorted(archive_root.glob(f"*/{normalized_hash}.json"), reverse=True):
            if not _is_within(path.resolve(strict=False), self.root):
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                if (
                    not isinstance(payload, dict)
                    or payload.get("schema_version") != _SCHEMA_VERSION
                ):
                    continue
                envelope = _deserialize_envelope(payload.get("message"))
                actual_hash = hashlib.sha256(envelope.message_id.encode("utf-8")).hexdigest()
                if actual_hash == normalized_hash:
                    return envelope
            except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
                continue
        return None

    def digest_cache_path(self, query: EmailQuery, model: str) -> Path:
        cache_identity = "|".join(
            (
                query.start_date.isoformat(),
                query.end_date.isoformat(),
                str(query.limit),
                str(model or "").strip(),
            )
        )
        cache_hash = hashlib.sha256(cache_identity.encode("utf-8")).hexdigest()[:20]
        filename = f"{query.start_date.isoformat()}_{query.end_date.isoformat()}_{cache_hash}.json"
        return self.root / "digests" / "ranges" / filename

    def daily_digest_path(self, digest_date: date) -> Path:
        return self.root / "digests" / "daily" / f"{digest_date.isoformat()}.json"

    def weekly_digest_path(self, digest_date: date) -> Path:
        iso_year, iso_week, _ = digest_date.isocalendar()
        return self.root / "digests" / "weekly" / f"{iso_year:04d}-W{iso_week:02d}.json"

    def load_digest(self, query: EmailQuery, model: str) -> EmailDigest | None:
        if query.refresh:
            return None
        path = self.digest_cache_path(query, model)
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            self._validate_digest_payload(payload, query, model)
            digest = payload["digest"]
            return EmailDigest(
                period_label=str(digest["period_label"]),
                message_count=int(digest["message_count"]),
                summary_text=str(digest["summary_text"]),
                source_message_ids=tuple(str(value) for value in digest["source_message_ids"]),
                from_cache=True,
            )
        except (OSError, UnicodeError, ValueError, TypeError, KeyError, json.JSONDecodeError):
            self._quarantine(path)
            return None

    def write_digest(self, query: EmailQuery, model: str, digest: EmailDigest) -> Path:
        path = self.digest_cache_path(query, model)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "cache": {
                "start_date": query.start_date.isoformat(),
                "end_date": query.end_date.isoformat(),
                "limit": query.limit,
                "model": str(model or "").strip(),
            },
            "digest": {
                "period_label": digest.period_label,
                "message_count": digest.message_count,
                "summary_text": digest.summary_text,
                "source_message_ids": list(digest.source_message_ids),
            },
        }
        _atomic_write_json(path, payload)
        return path

    def cleanup_expired(self, *, retention_days: int, dry_run: bool = False) -> list[Path]:
        if int(retention_days) <= 0:
            raise ValueError("retention_days must be positive")
        archive_root = self.root / "archive"
        if not archive_root.is_dir():
            return []
        cutoff = _timestamp(self._now()) - int(retention_days) * 86400
        deleted: list[Path] = []
        for candidate in sorted(archive_root.rglob("*.json")):
            resolved = candidate.resolve(strict=False)
            if not _is_within(resolved, self.root):
                continue
            try:
                expired = candidate.stat().st_mtime < cutoff
            except OSError:
                continue
            if not expired:
                continue
            if not _is_within(candidate.resolve(strict=False), self.root):
                continue
            if not dry_run:
                try:
                    candidate.unlink()
                except OSError:
                    continue
            deleted.append(candidate)
        return deleted

    def _validate_digest_payload(
        self,
        payload: object,
        query: EmailQuery,
        model: str,
    ) -> None:
        if not isinstance(payload, dict) or payload.get("schema_version") != _SCHEMA_VERSION:
            raise ValueError("unsupported digest cache schema")
        cache = payload["cache"]
        digest = payload["digest"]
        if not isinstance(cache, dict) or not isinstance(digest, dict):
            raise ValueError("invalid digest cache payload")
        expected = {
            "start_date": query.start_date.isoformat(),
            "end_date": query.end_date.isoformat(),
            "limit": query.limit,
            "model": str(model or "").strip(),
        }
        if cache != expected:
            raise ValueError("digest cache identity mismatch")
        required = {"period_label", "message_count", "summary_text", "source_message_ids"}
        if not required.issubset(digest) or not isinstance(digest["source_message_ids"], list):
            raise ValueError("invalid digest cache fields")

    def _quarantine(self, path: Path) -> None:
        resolved = path.resolve(strict=False)
        if not path.exists() or not _is_within(resolved, self.root):
            return
        timestamp = self._now().strftime("%Y%m%dT%H%M%S%f")
        target = self.root / "quarantine" / f"{timestamp}-{path.name}"
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target = target.with_name(f"{timestamp}-{uuid.uuid4().hex[:8]}-{path.name}")
        os.replace(path, target)


def _serialize_envelope(envelope: EmailEnvelope) -> dict[str, object]:
    return {
        "message_id": envelope.message_id,
        "subject": envelope.subject,
        "sender": envelope.sender,
        "recipients": list(envelope.recipients),
        "sent_at": envelope.sent_at.isoformat() if envelope.sent_at else None,
        "body_text": envelope.body_text,
        "attachments": [
            {
                "filename": attachment.filename,
                "content_type": attachment.content_type,
                "size_bytes": attachment.size_bytes,
            }
            for attachment in envelope.attachments
        ],
    }


def _deserialize_envelope(raw: object) -> EmailEnvelope:
    if not isinstance(raw, dict):
        raise ValueError("invalid archived email envelope")
    sent_at_raw = raw.get("sent_at")
    sent_at = datetime.fromisoformat(str(sent_at_raw)) if sent_at_raw else None
    attachments_raw = raw.get("attachments", [])
    if not isinstance(attachments_raw, list):
        raise ValueError("invalid archived email attachments")
    return EmailEnvelope(
        message_id=str(raw["message_id"]),
        subject=str(raw["subject"]),
        sender=str(raw["sender"]),
        recipients=tuple(str(value) for value in raw.get("recipients", [])),
        sent_at=sent_at,
        body_text=str(raw.get("body_text", "")),
        attachments=tuple(
            EmailAttachment(
                filename=str(attachment["filename"]),
                content_type=str(attachment["content_type"]),
                size_bytes=int(attachment["size_bytes"]),
            )
            for attachment in attachments_raw
            if isinstance(attachment, dict)
        ),
    )


def _envelope_date(envelope: EmailEnvelope, *, fallback: datetime) -> date:
    if envelope.sent_at is None:
        return _local_date(fallback)
    return _local_date(envelope.sent_at)


def _local_date(value: datetime) -> date:
    if value.tzinfo is None:
        return value.date()
    return value.astimezone(LOCAL_TIMEZONE).date()


def _atomic_write_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.parent / f".{path.name}.{uuid.uuid4().hex}.tmp"
    try:
        descriptor = os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink()
        except FileNotFoundError:
            pass


def _json_file_equals(path: Path, payload: dict[str, object]) -> bool:
    try:
        return json.loads(path.read_text(encoding="utf-8")) == payload
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False


def _timestamp(value: datetime) -> float:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


__all__ = ["EmailArchiveService"]
