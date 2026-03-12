"""Skill routing helpers."""

from __future__ import annotations

from typing import Iterable

from apps.qq_ai_bridge.skills.base import Skill, SkillContext, SkillResult


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
    """Dispatch the first skill that matches and handles the context."""
    for skill in skills:
        reason = _get_match_reason(skill, context)
        matched = False
        try:
            matched = bool(skill.can_handle(context))
        except Exception as e:
            context.log(f"[SKILL] check {skill.name} reason={reason} matched=error error={e}")
            continue

        context.log(f"[SKILL] check {skill.name} reason={reason} matched={matched}")
        if not matched:
            continue

        result = skill.handle(context)
        response_produced = bool(result.response_payload or result.response_text)
        context.log(
            f"[SKILL] result {skill.name} handled={result.handled} status={result.status} response_produced={response_produced}"
        )
        if result.handled:
            return result

    context.log("[SKILL] no skill handled the message")
    return None
