"""Schedule query skill."""

from __future__ import annotations

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import SCHEDULE_PATH
from apps.qq_ai_bridge.services.schedule_service import (
    detect_schedule_intent,
    format_today_schedule_reply,
    format_tomorrow_schedule_reply,
    query_today_schedule,
    query_tomorrow_schedule,
)
from apps.qq_ai_bridge.services.time_utils import get_now_local
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult


class ScheduleSkill:
    """Handle local schedule queries."""

    name = "schedule"

    def match_reason(self, context: SkillContext) -> str:
        if not context.is_private:
            return "not_private"
        intent = detect_schedule_intent(context.effective_text)
        if intent == "tomorrow_schedule":
            return "tomorrow_schedule_query"
        if intent == "today_schedule":
            return "today_schedule_query"
        return "not_schedule_query"

    def can_handle(self, context: SkillContext) -> bool:
        return context.is_private and detect_schedule_intent(context.effective_text) is not None

    def handle(self, context: SkillContext) -> SkillResult:
        intent = detect_schedule_intent(context.effective_text)
        now = get_now_local()

        if intent == "today_schedule":
            schedule_info = query_today_schedule(SCHEDULE_PATH, now=now)
            send_private_msg(context.user_id, format_today_schedule_reply(schedule_info))
            return SkillResult(handled=True, source=self.name)

        if intent == "tomorrow_schedule":
            schedule_info = query_tomorrow_schedule(SCHEDULE_PATH, now=now)
            send_private_msg(context.user_id, format_tomorrow_schedule_reply(schedule_info))
            return SkillResult(handled=True, source=self.name)

        return SkillResult(handled=False, source=self.name, status="ignore")
