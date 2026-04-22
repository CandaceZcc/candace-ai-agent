"""Skill routing helpers."""

from __future__ import annotations

import os
from typing import Iterable

from apps.qq_ai_bridge.skills.base import Skill, SkillContext, SkillResult


_VERBOSE_SKILL_LOG = (os.getenv("BRIDGE_LOG_LEVEL") or "info").strip().lower() == "debug"


def _get_match_reason(skill: Skill, context: SkillContext) -> str:
    """Return a best-effort match reason for debug logging."""
    reason_fn = getattr(skill, "match_reason", None)
    if callable(reason_fn):
        try:
            return str(reason_fn(context))
        except Exception as e:
            return f"match_reason_error:{e}"
    return "n/a"


def dispatch_skill(context: SkillContext, skills: Iterable[Skill]) -> SkillResult | None:
    """Dispatch the first skill that matches and handles the context.

    At ``BRIDGE_LOG_LEVEL=debug`` every probed skill gets a line. At the default
    level we instead print a single summary line once a skill matches (or at
    the end when none did), so ordinary traffic produces one [SKILL] line per
    inbound message instead of nine.
    """
    skipped: list[tuple[str, str]] = []
    for skill in skills:
        reason = _get_match_reason(skill, context)
        matched = False
        try:
            matched = bool(skill.can_handle(context))
        except Exception as e:
            context.log(f"[SKILL] check {skill.name} reason={reason} matched=error error={e}")
            continue

        if _VERBOSE_SKILL_LOG:
            context.log(f"[SKILL] check {skill.name} reason={reason} matched={matched}")

        if not matched:
            skipped.append((skill.name, reason))
            continue

        skipped_summary = ", ".join(f"{n}:{r}" for n, r in skipped) if skipped else "-"
        result = skill.handle(context)
        response_produced = bool(result.response_payload or result.response_text)
        context.log(
            f"[SKILL] -> {skill.name} handled={result.handled} status={result.status}"
            f" response_produced={response_produced} skipped=[{skipped_summary}]"
        )
        if result.handled:
            return result
        skipped.append((skill.name, f"handled=False:{result.status}"))

    skipped_summary = ", ".join(f"{n}:{r}" for n, r in skipped) if skipped else "-"
    context.log(f"[SKILL] no skill handled the message skipped=[{skipped_summary}]")
    return None
