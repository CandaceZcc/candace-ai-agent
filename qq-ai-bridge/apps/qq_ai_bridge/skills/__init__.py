"""Skill package for QQ bridge message handling."""

from apps.qq_ai_bridge.skills.registry import build_skill_registry
from apps.qq_ai_bridge.skills.router import dispatch_skill

__all__ = ["build_skill_registry", "dispatch_skill"]
