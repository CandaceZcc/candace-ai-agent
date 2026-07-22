"""Safe standard-library MIME parsing for read-only email digests."""

from __future__ import annotations

import hashlib
import re
from email import policy
from email.header import decode_header
from email.message import Message
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from html.parser import HTMLParser
from urllib.parse import urlparse

from apps.qq_ai_bridge.config.settings import EMAIL_MAX_BODY_CHARS
from apps.qq_ai_bridge.services.email_models import EmailAttachment, EmailEnvelope

_IGNORED_HTML_TAGS = {"script", "style", "noscript"}
_BLOCK_HTML_TAGS = {
    "br",
    "div",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "li",
    "p",
    "table",
    "td",
    "th",
    "tr",
}
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f\x7f]")
_WHITESPACE_RE = re.compile(r"\s+")


class _VisibleHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._ignored_depth = 0
        self._anchor_targets: list[str | None] = []
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in _IGNORED_HTML_TAGS:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag in _BLOCK_HTML_TAGS:
            self._chunks.append("\n")
        if tag == "a":
            href = dict(attrs).get("href")
            self._anchor_targets.append(_safe_http_url(href))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() == "a":
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in _IGNORED_HTML_TAGS:
            self._ignored_depth = max(0, self._ignored_depth - 1)
            return
        if self._ignored_depth:
            return
        if tag == "a" and self._anchor_targets:
            target = self._anchor_targets.pop()
            if target:
                self._chunks.append(f" ({target})")
        if tag in _BLOCK_HTML_TAGS:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if not self._ignored_depth:
            self._chunks.append(data)

    def text(self) -> str:
        return _normalize_text("".join(self._chunks))


def parse_email(
    raw_message: bytes,
    *,
    max_body_chars: int = EMAIL_MAX_BODY_CHARS,
) -> EmailEnvelope:
    """Parse one raw MIME message without executing or fetching external content."""
    raw_bytes = bytes(raw_message)
    message = BytesParser(policy=policy.default).parsebytes(raw_bytes)
    plain_parts, html_parts, attachments = _collect_parts(message)
    body_text = "\n\n".join(plain_parts)
    if not body_text and html_parts:
        body_text = "\n\n".join(_html_to_text(value) for value in html_parts)
    body_text = _normalize_text(body_text)[: max(0, int(max_body_chars))]

    return EmailEnvelope(
        message_id=_message_id(message, raw_bytes),
        subject=_decode_header_value(message.get("Subject")) or "(no subject)",
        sender=_format_single_address(message.get("From")) or "(unknown sender)",
        recipients=_format_addresses(message.get_all("To", [])),
        sent_at=_parse_date(message.get("Date")),
        body_text=body_text,
        attachments=tuple(attachments),
    )


def _collect_parts(
    message: Message,
) -> tuple[list[str], list[str], list[EmailAttachment]]:
    plain_parts: list[str] = []
    html_parts: list[str] = []
    attachments: list[EmailAttachment] = []
    for part in message.walk():
        if part.is_multipart():
            continue
        disposition = str(part.get_content_disposition() or "").lower()
        if disposition == "attachment":
            attachments.append(_attachment_metadata(part))
            continue
        if disposition == "inline":
            continue
        content_type = part.get_content_type().lower()
        if content_type == "text/plain":
            plain_parts.append(_decode_text_part(part))
        elif content_type == "text/html":
            html_parts.append(_decode_text_part(part))
    return plain_parts, html_parts, attachments


def _decode_text_part(part: Message) -> str:
    payload = part.get_payload(decode=True)
    if payload is None:
        raw_payload = part.get_payload()
        return raw_payload if isinstance(raw_payload, str) else ""
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")


def _attachment_metadata(part: Message) -> EmailAttachment:
    filename = _sanitize_filename(_decode_header_value(part.get_filename()))
    payload = part.get_payload(decode=True) or b""
    return EmailAttachment(
        filename=filename,
        content_type=part.get_content_type().lower(),
        size_bytes=len(payload),
    )


def _decode_header_value(value: object) -> str:
    if value is None:
        return ""
    decoded: list[str] = []
    try:
        pieces = decode_header(str(value))
    except (LookupError, ValueError):
        return _normalize_header(str(value))
    for piece, charset in pieces:
        if isinstance(piece, str):
            decoded.append(piece)
            continue
        try:
            decoded.append(piece.decode(charset or "utf-8", errors="replace"))
        except LookupError:
            decoded.append(piece.decode("utf-8", errors="replace"))
    return _normalize_header("".join(decoded))


def _format_single_address(value: object) -> str:
    addresses = _format_addresses([value] if value is not None else [])
    return addresses[0] if addresses else ""


def _format_addresses(values: list[object]) -> tuple[str, ...]:
    decoded_values = [_decode_header_value(value) for value in values]
    formatted: list[str] = []
    for display_name, address in getaddresses(decoded_values):
        safe_name = _normalize_header(display_name)
        safe_address = _normalize_header(address)
        if safe_name and safe_address:
            formatted.append(f"{safe_name} <{safe_address}>")
        elif safe_address or safe_name:
            formatted.append(safe_address or safe_name)
    return tuple(formatted)


def _parse_date(value: object):
    if value is None:
        return None
    try:
        return parsedate_to_datetime(str(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _message_id(message: Message, raw_message: bytes) -> str:
    value = _normalize_header(str(message.get("Message-ID") or ""))
    if value:
        return value
    return f"sha256:{hashlib.sha256(raw_message).hexdigest()}"


def _sanitize_filename(filename: str) -> str:
    normalized = _CONTROL_CHARS_RE.sub("", filename).replace("\\", "/")
    safe_name = normalized.rsplit("/", 1)[-1].strip().strip(".")
    return safe_name or "attachment"


def _html_to_text(value: str) -> str:
    parser = _VisibleHTMLParser()
    try:
        parser.feed(value)
        parser.close()
    except (TypeError, ValueError):
        return ""
    return parser.text()


def _safe_http_url(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value.strip())
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        return None
    return value.strip()


def _normalize_text(value: str) -> str:
    lines = [_WHITESPACE_RE.sub(" ", line).strip() for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _normalize_header(value: str) -> str:
    return _WHITESPACE_RE.sub(" ", _CONTROL_CHARS_RE.sub("", value)).strip()


__all__ = ["parse_email"]
