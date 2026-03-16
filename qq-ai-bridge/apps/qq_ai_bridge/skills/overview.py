"""Schedule and reminder overview skill."""

from __future__ import annotations

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import REMINDERS_PATH, SCHEDULE_PATH
from apps.qq_ai_bridge.services.reminder_service import build_tomorrow_reminders_reply, query_tomorrow_reminders
from apps.qq_ai_bridge.services.reminder_store import ReminderStore
from apps.qq_ai_bridge.services.schedule_service import detect_schedule_intent, format_tomorrow_schedule_reply, query_tomorrow_schedule
from apps.qq_ai_bridge.services.time_utils import get_now_local
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult


REMINDER_STORE = ReminderStore(REMINDERS_PATH)


class OverviewSkill:
    """Handle local tomorrow schedule + reminder overview queries."""

    name = "overview"

    def match_reason(self, context: SkillContext) -> str:
        if not context.is_private:
            return "not_private"
        return "tomorrow_schedule_reminder_query" if detect_schedule_intent(context.effective_text) == "tomorrow_overview" else "not_overview_query"

    def can_handle(self, context: SkillContext) -> bool:
        return context.is_private and detect_schedule_intent(context.effective_text) == "tomorrow_overview"

    def handle(self, context: SkillContext) -> SkillResult:
        now = get_now_local()
        pending_items = REMINDER_STORE.list_pending(context.user_id)
        schedule_info = query_tomorrow_schedule(SCHEDULE_PATH, now=now)
        reminder_info = query_tomorrow_reminders(pending_items, now=now)
        context.log(
            f"[OVERVIEW] tomorrow date={schedule_info['date']}"
            f" reminder_count={len(reminder_info['items'])}"
            f" schedule_count={len(schedule_info.get('courses', []))}"
        )
        send_private_msg(
            context.user_id,
            f"{format_tomorrow_schedule_reply(schedule_info)}\n\n{build_tomorrow_reminders_reply(pending_items, now=now)}",
        )
        return SkillResult(handled=True, source=self.name)
