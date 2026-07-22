"""Read-only, bounded IMAP access for campus email digests."""

from __future__ import annotations

import imaplib
from contextlib import suppress
from datetime import date, timedelta
from typing import Callable

from apps.qq_ai_bridge.services.email_models import (
    EmailEnvelope,
    EmailFetchedMessage,
    EmailQuery,
    EmailUidBatch,
    EmailUidSnapshot,
)
from apps.qq_ai_bridge.services.email_parser import parse_email

EmailParser = Callable[..., EmailEnvelope]
_IMAP_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)


class EmailImapError(RuntimeError):
    """An IMAP failure with a stable, credential-safe error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(message)


class EmailImapService:
    def __init__(
        self,
        *,
        host: str,
        port: int,
        username: str,
        password: str,
        mailbox: str,
        timeout_seconds: int,
        parser: EmailParser = parse_email,
        max_body_chars: int,
    ) -> None:
        self._host = str(host or "").strip()
        self._port = int(port)
        self._username = str(username or "").strip()
        self._password = str(password or "")
        self._mailbox = str(mailbox or "").strip()
        self._timeout_seconds = int(timeout_seconds)
        self._parser = parser
        self._max_body_chars = int(max_body_chars)

    def fetch(self, query: EmailQuery) -> list[EmailEnvelope]:
        self._validate_config()
        connection = None
        try:
            connection = self._connect()
            self._login(connection)
            self._expect_ok(
                connection.select(self._mailbox, readonly=True),
                operation="select",
            )
            search_result = connection.search(
                None,
                "SINCE",
                _format_imap_date(query.start_date),
                "BEFORE",
                _format_imap_date(query.end_date + timedelta(days=1)),
            )
            _, search_data = self._expect_ok(search_result, operation="search")
            message_ids = _search_ids(search_data)
            newest_ids = message_ids[-query.limit :][::-1]
            envelopes = [self._fetch_one(connection, message_id) for message_id in newest_ids]
            return list(reversed(envelopes))
        except EmailImapError:
            raise
        except OSError as exc:
            raise self._network_error() from exc
        except imaplib.IMAP4.error as exc:
            raise self._protocol_error("command") from exc
        finally:
            if connection is not None:
                with suppress(Exception):
                    connection.logout()

    def fetch_new(self, *, last_uid: int, limit: int) -> EmailUidBatch:
        self._validate_config()
        if int(last_uid) < 0:
            raise ValueError("last_uid must not be negative")
        if int(limit) <= 0:
            raise ValueError("limit must be positive")
        connection = None
        try:
            connection = self._connect()
            self._login(connection)
            self._expect_ok(
                connection.select(self._mailbox, readonly=True),
                operation="select",
            )
            uid_validity = _uid_validity(connection.response("UIDVALIDITY"))
            if not uid_validity:
                raise self._protocol_error("uidvalidity")
            search_result = connection.uid(
                "search",
                None,
                "UID",
                f"{int(last_uid) + 1}:*",
            )
            _, search_data = self._expect_ok(search_result, operation="uid_search")
            message_ids = _new_uid_ids(
                search_data,
                last_uid=int(last_uid),
                limit=int(limit),
            )
            messages = tuple(
                EmailFetchedMessage(
                    uid=int(message_id),
                    envelope=self._fetch_one_uid(connection, message_id),
                )
                for message_id in message_ids
            )
            return EmailUidBatch(uid_validity=uid_validity, messages=messages)
        except EmailImapError:
            raise
        except OSError as exc:
            raise self._network_error() from exc
        except imaplib.IMAP4.error as exc:
            raise self._protocol_error("uid_command") from exc
        finally:
            if connection is not None:
                with suppress(Exception):
                    connection.logout()

    def snapshot_cursor(self) -> EmailUidSnapshot:
        self._validate_config()
        connection = None
        try:
            connection = self._connect()
            self._login(connection)
            self._expect_ok(
                connection.select(self._mailbox, readonly=True),
                operation="select",
            )
            uid_validity = _uid_validity(connection.response("UIDVALIDITY"))
            if not uid_validity:
                raise self._protocol_error("uidvalidity")
            search_result = connection.uid("search", None, "ALL")
            _, search_data = self._expect_ok(search_result, operation="uid_search")
            latest_uid = max(
                (int(value) for value in _search_ids(search_data) if value.isdigit()),
                default=0,
            )
            return EmailUidSnapshot(uid_validity=uid_validity, latest_uid=latest_uid)
        except EmailImapError:
            raise
        except OSError as exc:
            raise self._network_error() from exc
        except imaplib.IMAP4.error as exc:
            raise self._protocol_error("uid_command") from exc
        finally:
            if connection is not None:
                with suppress(Exception):
                    connection.logout()

    def _validate_config(self) -> None:
        if (
            not self._host
            or not self._username
            or not self._password
            or not self._mailbox
            or not 1 <= self._port <= 65535
            or self._timeout_seconds <= 0
            or self._max_body_chars <= 0
        ):
            raise EmailImapError(
                "email_config_error",
                "Email IMAP configuration is incomplete or invalid",
            )

    def _connect(self):
        try:
            return imaplib.IMAP4_SSL(
                self._host,
                self._port,
                timeout=self._timeout_seconds,
            )
        except (OSError, imaplib.IMAP4.error) as exc:
            raise self._network_error() from exc

    def _login(self, connection) -> None:
        try:
            status, _ = connection.login(self._username, self._password)
        except imaplib.IMAP4.error as exc:
            raise EmailImapError(
                "email_auth_error",
                f"Email IMAP authentication failed for host {self._host}",
            ) from exc
        except OSError as exc:
            raise self._network_error() from exc
        if _status_text(status) != "OK":
            raise EmailImapError(
                "email_auth_error",
                f"Email IMAP authentication failed for host {self._host}",
            )

    def _fetch_one(self, connection, message_id: bytes) -> EmailEnvelope:
        _, fetch_data = self._expect_ok(
            connection.fetch(message_id, "(RFC822)"),
            operation="fetch",
        )
        raw_message = _raw_message(fetch_data)
        if raw_message is None:
            raise self._protocol_error("fetch")
        try:
            return self._parser(raw_message, max_body_chars=self._max_body_chars)
        except EmailImapError:
            raise
        except Exception as exc:
            raise EmailImapError(
                "email_parse_error",
                "Unable to parse a fetched email message",
            ) from exc

    def _fetch_one_uid(self, connection, message_id: bytes) -> EmailEnvelope:
        _, fetch_data = self._expect_ok(
            connection.uid("fetch", message_id, "(RFC822)"),
            operation="uid_fetch",
        )
        raw_message = _raw_message(fetch_data)
        if raw_message is None:
            raise self._protocol_error("uid_fetch")
        try:
            return self._parser(raw_message, max_body_chars=self._max_body_chars)
        except EmailImapError:
            raise
        except Exception as exc:
            raise EmailImapError(
                "email_parse_error",
                "Unable to parse a fetched email message",
            ) from exc

    def _expect_ok(self, result, *, operation: str):
        try:
            status, data = result
        except (TypeError, ValueError) as exc:
            raise self._protocol_error(operation) from exc
        if _status_text(status) != "OK":
            raise self._protocol_error(operation)
        return status, data

    def _network_error(self) -> EmailImapError:
        return EmailImapError(
            "email_network_error",
            f"Unable to reach email IMAP host {self._host}",
        )

    def _protocol_error(self, operation: str) -> EmailImapError:
        return EmailImapError(
            "email_protocol_error",
            f"Email IMAP {operation} failed for mailbox {self._mailbox}",
        )


def _format_imap_date(value: date) -> str:
    return f"{value.day:02d}-{_IMAP_MONTHS[value.month - 1]}-{value.year:04d}"


def _status_text(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("ascii", errors="replace").upper()
    return str(value or "").upper()


def _search_ids(search_data) -> list[bytes]:
    if not search_data:
        return []
    first = search_data[0]
    if isinstance(first, str):
        first = first.encode("ascii", errors="ignore")
    if not isinstance(first, bytes):
        return []
    return first.split()


def _new_uid_ids(search_data, *, last_uid: int, limit: int) -> list[bytes]:
    values = {
        int(value)
        for value in _search_ids(search_data)
        if value.isdigit() and int(value) > last_uid
    }
    return [str(value).encode("ascii") for value in sorted(values)[:limit]]


def _uid_validity(response) -> str:
    try:
        _, data = response
    except (TypeError, ValueError):
        return ""
    if not data:
        return ""
    value = data[0]
    if isinstance(value, bytes):
        value = value.decode("ascii", errors="ignore")
    normalized = str(value or "").strip()
    return normalized if normalized.isdigit() else ""


def _raw_message(fetch_data) -> bytes | None:
    for item in fetch_data or ():
        if isinstance(item, tuple) and len(item) >= 2 and isinstance(item[1], bytes):
            return item[1]
    return None


__all__ = ["EmailImapError", "EmailImapService"]
