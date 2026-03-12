"""Skill registry construction."""

from __future__ import annotations

from apps.qq_ai_bridge.skills.browser_agent import BrowserAgentSkill
from apps.qq_ai_bridge.skills.chat import ChatSkill
from apps.qq_ai_bridge.skills.desktop_agent import DesktopAgentSkill
from apps.qq_ai_bridge.skills.file_understanding import FileUnderstandingSkill
from apps.qq_ai_bridge.skills.image_understanding import ImageUnderstandingSkill


def build_skill_registry():
    """Build the default ordered skill registry."""
    return [
        ImageUnderstandingSkill(),
        FileUnderstandingSkill(),
        DesktopAgentSkill(),
        BrowserAgentSkill(),
        ChatSkill(),
    ]
