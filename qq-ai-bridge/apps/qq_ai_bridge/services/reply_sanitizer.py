"""Sanitize outbound replies before they are sent to QQ."""

import re

BLOCKED_EXACT = {
    "",
    "completed",
    "processing",
    "done",
    "null",
    "请求超时",
}

BLOCKED_PHRASES = (
    "请求超时",
    "completed",
    "processing",
    "done",
    "null",
)


def sanitize_outbound_reply(text: str) -> str:
    """Remove empty or status-only replies and normalize spacing."""
    normalized = str(text or "").replace("\r\n", "\n").replace("\r", "\n")
    flat = re.sub(r"\s+", " ", normalized.replace("\n", " ")).strip()
    if not flat:
        return ""

    lowered = flat.lower()
    if lowered in BLOCKED_EXACT:
        return ""
    if _is_status_only(lowered):
        return ""

    cleaned = flat
    for phrase in BLOCKED_PHRASES:
        cleaned = re.sub(re.escape(phrase), " ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" \t\r\n,.;:!?，。！？、~`'\"()[]{}")
    if not cleaned:
        return ""
    if _is_only_punctuation(cleaned):
        return ""

    lines = []
    for line in normalized.split("\n"):
        line = re.sub(r"[ \t]+", " ", line).strip()
        if line:
            lines.append(line)
    return "\n".join(lines)


def _is_status_only(text: str) -> bool:
    parts = [part for part in re.split(r"[\s,.;:!?，。！？、/|_-]+", text) if part]
    if not parts:
        return True
    return all(part in BLOCKED_EXACT for part in parts)


def _is_only_punctuation(text: str) -> bool:
    return re.fullmatch(r"[\W_]+", text, flags=re.UNICODE) is not None
