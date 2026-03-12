"""Skill interfaces and shared context objects."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Optional, Protocol


@dataclass
class SkillContext:
    """Normalized webhook context passed to skills."""

    data: dict
    post_type: str
    message_type: str
    user_id: int | None
    self_id: int | None
    group_id: int | None
    group_config: dict
    should_log: bool
    msg: str
    normalized_msg: str
    mentioned_self: bool
    image_inputs: dict
    file_info: Optional[dict]
    logger: Callable[..., None]
    timestamp: int = 0

    @property
    def is_private(self) -> bool:
        """Return whether this is a private message."""
        return self.message_type == "private"

    @property
    def is_group(self) -> bool:
        """Return whether this is a group message."""
        return self.message_type == "group"

    def log(self, *args: Any) -> None:
        """Emit a log line through the webhook logger."""
        self.logger(*args)


@dataclass
class SkillResult:
    """Result of dispatching a skill."""

    handled: bool
    source: str = ""
    status: str = "ok"
    response_payload: Optional[dict] = None
    response_text: Optional[str] = None
    already_sent: bool = True


class Skill(Protocol):
    """Protocol implemented by all bridge skills."""

    name: str

    def can_handle(self, context: SkillContext) -> bool:
        """Return whether the skill should handle the message."""

    def handle(self, context: SkillContext) -> SkillResult:
        """Handle the message and return the dispatch result."""
