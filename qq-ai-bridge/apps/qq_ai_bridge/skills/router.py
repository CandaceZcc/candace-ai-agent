"""Skill routing helpers."""

from __future__ import annotations

from typing import Iterable

from apps.qq_ai_bridge.skills.base import Skill, SkillContext, SkillResult


def dispatch_skill(context: SkillContext, skills: Iterable[Skill]) -> SkillResult | None:
    """Dispatch the first matching skill."""
    for skill in skills:
        if not skill.can_handle(context):
            continue
        context.log(f"[SKILL] dispatch -> {skill.name}")
        return skill.handle(context)
    return None
