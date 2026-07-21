"""Skill registry construction."""

from __future__ import annotations

from importlib import import_module
from typing import Any

_SKILL_SPECS = (
    ("apps.qq_ai_bridge.skills.draw", "DrawSkill"),
    ("apps.qq_ai_bridge.skills.image_understanding", "ImageUnderstandingSkill"),
    ("apps.qq_ai_bridge.skills.file_understanding", "FileUnderstandingSkill"),
    ("apps.qq_ai_bridge.skills.desktop_agent", "DesktopAgentSkill"),
    ("apps.qq_ai_bridge.skills.browser_agent", "BrowserAgentSkill"),
    ("apps.qq_ai_bridge.skills.weather", "WeatherSkill"),
    ("apps.qq_ai_bridge.skills.reminder", "ReminderSkill"),
    ("apps.qq_ai_bridge.skills.overview", "OverviewSkill"),
    ("apps.qq_ai_bridge.skills.schedule", "ScheduleSkill"),
    ("apps.qq_ai_bridge.skills.email", "EmailSkill"),
    ("apps.qq_ai_bridge.skills.chat", "ChatSkill"),
)


def _load_skill_class(module_name: str, class_name: str) -> type[Any] | None:
    try:
        module = import_module(module_name)
        return getattr(module, class_name)
    except Exception as exc:
        print(f"[SKILL_REGISTRY] skip {module_name}.{class_name}: {exc}")
        return None


def build_skill_registry():
    """Build the default ordered skill registry."""
    skills = []
    for module_name, class_name in _SKILL_SPECS:
        skill_cls = _load_skill_class(module_name, class_name)
        if skill_cls is None:
            continue
        try:
            skills.append(skill_cls())
        except Exception as exc:
            print(f"[SKILL_REGISTRY] init_failed {module_name}.{class_name}: {exc}")
    return skills
