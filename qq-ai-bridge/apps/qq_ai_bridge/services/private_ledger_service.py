"""Owner-only private ledger parsing and continuation helpers."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.qq_ai_bridge.config.settings import OWNER_QQ

LEDGER_PAGE_CHAR_LIMIT = 360
LEDGER_MAX_SEND_PARTS = 5

_LEDGER_KEYWORDS = ("记账", "账单", "开销")
_CONTINUE_COMMANDS = {
    "继续",
    "展开",
    "下一页",
    "继续输出",
    "继续发",
    "接着发",
    "重新输出",
    "重新发",
    "输出完整账单",
    "完整账单",
}
_FULL_COMMANDS = {"输出完整账单", "完整账单", "全部账单", "发完整账单", "完整输出", "重新输出", "重新发"}
_AMOUNT_EXPR_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)(?:\s*\+\s*(\d+(?:\.\d+)?))*\s*$")
_LEDGER_LINE_RE = re.compile(r"^\s*([^:：\n]{1,60})[:：]\s*([0-9][0-9+.\s]*)\s*$")
_INLINE_LEDGER_ENTRY_RE = re.compile(
    r"(?P<name>[^:：\n]{1,80})[:：]\s*(?P<expr>\d[\d+.\s]*?)(?=\s+[^:：\n]{1,80}[:：]|$)"
)
_DATE_RANGE_RE = re.compile(r"(\d{1,2}(?:\.\d{1,2})?\s*[-~到至]\s*\d{1,2}(?:\.\d{1,2})?)")


@dataclass(frozen=True)
class LedgerItem:
    name: str
    expression: str
    amount: Decimal


@dataclass
class LedgerArtifact:
    user_id: str
    title: str
    original_text: str
    items: list[LedgerItem]
    total: Decimal
    pages: list[str]
    cursor: int
    created_at: int
    summary: str


_PRIVATE_LEDGER_ARTIFACTS: dict[str, LedgerArtifact] = {}


def maybe_handle_private_ledger_command(user_id: Any, text: str) -> dict[str, Any] | None:
    """Parse owner private ledger requests or continue the last ledger artifact."""
    if str(user_id or "") != str(OWNER_QQ):
        return None

    query = str(text or "").strip()
    if not query:
        return None

    if _is_continue_command(query):
        return _continue_ledger(user_id, full=_is_full_command(query))

    if not _looks_like_ledger_request(query):
        return None

    artifact = parse_ledger_text(user_id, query)
    if not artifact:
        return None

    _PRIVATE_LEDGER_ARTIFACTS[str(user_id)] = artifact
    first_page = artifact.pages[0] if artifact.pages else artifact.summary
    artifact.cursor = 1
    if artifact.cursor < len(artifact.pages):
        first_page = f"{first_page}\n发送继续查看剩余 {len(artifact.pages) - artifact.cursor} 页"
    return {
        "handled": True,
        "mode": "parsed",
        "reply": first_page,
        "history_reply": f"[ledger_artifact] {artifact.summary}",
        "force_parts": None,
        "parts_total": len(artifact.pages),
        "summary": artifact.summary,
    }


def parse_ledger_text(user_id: Any, text: str) -> LedgerArtifact | None:
    """Build a ledger artifact from colon-separated amount lines."""
    items: list[LedgerItem] = []
    for raw_name, raw_expression in _iter_ledger_entries(text):
        name = _clean_item_name(raw_name)
        expression = re.sub(r"\s+", "", raw_expression)
        amount = _eval_amount_expression(expression)
        if not name or amount is None:
            continue
        items.append(LedgerItem(name=name, expression=expression, amount=amount))

    if not items:
        return None

    total = sum((item.amount for item in items), Decimal("0"))
    title = _extract_ledger_title(text)
    rendered = _render_ledger(title, items, total)
    pages = _paginate_ledger(rendered)
    summary = f"{title}，共 {_format_amount(total)} 元，{len(items)} 项"
    return LedgerArtifact(
        user_id=str(user_id),
        title=title,
        original_text=str(text or ""),
        items=items,
        total=total,
        pages=pages,
        cursor=0,
        created_at=int(time.time()),
        summary=summary,
    )


def _continue_ledger(user_id: Any, *, full: bool) -> dict[str, Any]:
    artifact = _PRIVATE_LEDGER_ARTIFACTS.get(str(user_id))
    if not artifact:
        return {
            "handled": True,
            "mode": "missing",
            "reply": "没有可继续的账单。先发一段记账内容给我。",
            "history_reply": "[ledger_artifact_missing]",
            "force_parts": None,
        }

    if full:
        pages = artifact.pages[:LEDGER_MAX_SEND_PARTS]
        artifact.cursor = min(len(artifact.pages), LEDGER_MAX_SEND_PARTS)
        reply = "\n\n".join(pages)
        if artifact.cursor < len(artifact.pages):
            reply = f"{reply}\n\n还有 {len(artifact.pages) - artifact.cursor} 页，发送继续查看剩余"
        return {
            "handled": True,
            "mode": "full",
            "reply": reply,
            "history_reply": f"[ledger_artifact_full] {artifact.summary}",
            "force_parts": min(len(pages), LEDGER_MAX_SEND_PARTS),
            "parts_total": len(pages),
            "summary": artifact.summary,
        }

    if artifact.cursor >= len(artifact.pages):
        return {
            "handled": True,
            "mode": "done",
            "reply": "账单已经发完了。",
            "history_reply": f"[ledger_artifact_done] {artifact.summary}",
            "force_parts": None,
            "summary": artifact.summary,
        }

    page = artifact.pages[artifact.cursor]
    artifact.cursor += 1
    if artifact.cursor < len(artifact.pages):
        page = f"{page}\n发送继续查看剩余 {len(artifact.pages) - artifact.cursor} 页"
    return {
        "handled": True,
        "mode": "continued",
        "reply": page,
        "history_reply": f"[ledger_artifact_continue] {artifact.summary}",
        "force_parts": None,
        "parts_total": len(artifact.pages),
        "summary": artifact.summary,
    }


def _looks_like_ledger_request(text: str) -> bool:
    if not any(keyword in text for keyword in _LEDGER_KEYWORDS):
        return False
    return any(_eval_amount_expression(re.sub(r"\s+", "", expr)) is not None for _, expr in _iter_ledger_entries(text))


def _iter_ledger_entries(text: str) -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    raw_text = str(text or "")
    for raw_line in raw_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        line_match = _LEDGER_LINE_RE.match(line)
        if line_match:
            entries.append((line_match.group(1), line_match.group(2)))
            continue
        for match in _INLINE_LEDGER_ENTRY_RE.finditer(line):
            entries.append((match.group("name"), match.group("expr")))
    if entries:
        return entries

    compact_text = re.sub(r"\s+", " ", raw_text).strip()
    return [(match.group("name"), match.group("expr")) for match in _INLINE_LEDGER_ENTRY_RE.finditer(compact_text)]


def _is_continue_command(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return compact in _CONTINUE_COMMANDS or compact in _FULL_COMMANDS


def _is_full_command(text: str) -> bool:
    compact = re.sub(r"\s+", "", str(text or ""))
    return compact in _FULL_COMMANDS


def _eval_amount_expression(expression: str) -> Decimal | None:
    expr = str(expression or "").strip()
    if not expr or not _AMOUNT_EXPR_RE.match(expr):
        return None
    total = Decimal("0")
    try:
        for part in expr.split("+"):
            total += Decimal(part.strip())
    except (InvalidOperation, ValueError):
        return None
    return total


def _extract_ledger_title(text: str) -> str:
    first_line = next((line.strip() for line in str(text or "").splitlines() if line.strip()), "")
    date_match = _DATE_RANGE_RE.search(first_line)
    period = re.sub(r"\s+", "", date_match.group(1)) if date_match else ""
    if period:
        return f"{period} 额外开销"
    return "额外开销"


def _clean_item_name(name: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(name or "")).strip(" -—\t")
    cleaned = re.sub(r"^.*[）)]\s*", "", cleaned).strip()
    cleaned = re.sub(r"^记账\s*\d{0,2}(?:\.\d{1,2})?(?:\s*[-~到至]\s*\d{1,2}(?:\.\d{1,2})?)?\s*", "", cleaned)
    cleaned = re.sub(r"^(?:[-*+]\s+|\d+[.)、]\s+)", "", cleaned).strip()
    return cleaned[:40]


def _format_amount(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(int(normalized))
    return format(normalized, "f").rstrip("0").rstrip(".")


def _render_ledger(title: str, items: list[LedgerItem], total: Decimal) -> str:
    lines = [f"{title}，共 {_format_amount(total)} 元"]
    for idx, item in enumerate(items, start=1):
        amount = _format_amount(item.amount)
        if item.expression != amount:
            lines.append(f"{idx}. {item.name} {amount} ({item.expression})")
        else:
            lines.append(f"{idx}. {item.name} {amount}")
    return "\n".join(lines)


def _paginate_ledger(text: str) -> list[str]:
    lines = [line for line in str(text or "").splitlines() if line.strip()]
    if not lines:
        return []

    pages: list[str] = []
    current: list[str] = []
    current_len = 0
    for line in lines:
        projected = current_len + len(line) + (1 if current else 0)
        if current and projected > LEDGER_PAGE_CHAR_LIMIT:
            pages.append("\n".join(current))
            current = [line]
            current_len = len(line)
        else:
            current.append(line)
            current_len = projected
    if current:
        pages.append("\n".join(current))
    return pages


__all__ = [
    "LEDGER_MAX_SEND_PARTS",
    "_PRIVATE_LEDGER_ARTIFACTS",
    "maybe_handle_private_ledger_command",
    "parse_ledger_text",
]
