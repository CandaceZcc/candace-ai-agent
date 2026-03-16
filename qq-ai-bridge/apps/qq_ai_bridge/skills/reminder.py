"""Private reminder skill."""

from __future__ import annotations

import traceback

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import REMINDERS_PATH
from apps.qq_ai_bridge.services.reminder_service import (
    CLEAR_COMMANDS,
    HELP_COMMANDS,
    LIST_COMMANDS,
    HELP_TEXT,
    build_add_success_message,
    build_done_list_message,
    build_list_message,
    build_next_pending_message,
    build_tomorrow_reminders_reply,
    detect_reminder_intent,
    is_reminder_command,
    normalize_text,
    parse_delete_command,
    parse_reminder_commands,
    query_tomorrow_reminders,
)
from apps.qq_ai_bridge.services.reminder_store import ReminderStore
from apps.qq_ai_bridge.services.time_utils import get_now_local
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult


REMINDER_STORE = ReminderStore(REMINDERS_PATH)


class ReminderSkill:
    """Handle private reminder commands before chat fallback."""

    name = "reminder"

    def match_reason(self, context: SkillContext) -> str:
        if not context.is_private:
            return "not_private"
        intent = detect_reminder_intent(context.effective_text)
        if intent:
            return intent.reason
        return "not_reminder_command"

    def can_handle(self, context: SkillContext) -> bool:
        return context.is_private and is_reminder_command(context.effective_text)

    def handle(self, context: SkillContext) -> SkillResult:
        text = context.effective_text
        normalized = normalize_text(text)
        intent = detect_reminder_intent(text)
        try:
            if intent is None:
                return SkillResult(handled=False, source=self.name, status="ignore")

            if normalized in HELP_COMMANDS:
                send_private_msg(context.user_id, HELP_TEXT)
                context.log("[REMINDER_QUERY] answered_without_ocai=True")
                return SkillResult(handled=True, source=self.name)

            if intent.kind == "list_pending" or normalized in LIST_COMMANDS:
                context.log("[REMINDER_QUERY] intent=list_pending")
                send_private_msg(context.user_id, build_list_message(REMINDER_STORE.list_pending(context.user_id)))
                context.log("[REMINDER_QUERY] answered_without_ocai=True")
                return SkillResult(handled=True, source=self.name)

            if intent.kind == "recent_done":
                context.log("[REMINDER_QUERY] intent=recent_done")
                send_private_msg(context.user_id, build_done_list_message(REMINDER_STORE.list_done(context.user_id, limit=5)))
                context.log("[REMINDER_QUERY] answered_without_ocai=True")
                return SkillResult(handled=True, source=self.name)

            if intent.kind == "next_pending":
                context.log("[REMINDER_QUERY] intent=next_pending")
                next_item = REMINDER_STORE.get_next_pending(user_id=context.user_id)
                send_private_msg(context.user_id, build_next_pending_message(next_item))
                context.log("[REMINDER_QUERY] answered_without_ocai=True")
                return SkillResult(handled=True, source=self.name)

            if intent.kind == "tomorrow_reminders":
                context.log("[REMINDER_QUERY] intent=tomorrow_reminders")
                pending_items = REMINDER_STORE.list_pending(context.user_id)
                tomorrow_query = query_tomorrow_reminders(pending_items, now=get_now_local())
                context.log(
                    f"[REMINDER_QUERY] tomorrow date={tomorrow_query['date']}"
                    f" weekday={tomorrow_query['weekday_cn']}"
                    f" pending_count={len(tomorrow_query['items'])}"
                    " schedule_count=0"
                )
                reply = build_tomorrow_reminders_reply(pending_items, now=get_now_local())
                send_private_msg(context.user_id, reply)
                context.log("[REMINDER_QUERY] answered_without_ocai=True")
                return SkillResult(handled=True, source=self.name)

            delete_id = parse_delete_command(text)
            if intent.kind == "delete" and delete_id is not None:
                cancelled = REMINDER_STORE.cancel_reminder(delete_id, user_id=context.user_id)
                reply = f"已取消提醒 [{delete_id}]" if cancelled else f"未找到待触发提醒 [{delete_id}]"
                send_private_msg(context.user_id, reply)
                context.log("[REMINDER_QUERY] answered_without_ocai=True")
                return SkillResult(handled=True, source=self.name)

            if intent.kind == "clear" or normalized in CLEAR_COMMANDS:
                count = REMINDER_STORE.clear_pending(user_id=context.user_id)
                send_private_msg(context.user_id, f"已清空 {count} 条待触发提醒。")
                context.log("[REMINDER_QUERY] answered_without_ocai=True")
                return SkillResult(handled=True, source=self.name)

            if intent.kind == "add":
                parsed_items = parse_reminder_commands(text, now=get_now_local())
                added_items = [
                    REMINDER_STORE.add_reminder(
                        user_id=context.user_id,
                        trigger_at=parsed.trigger_at,
                        text=parsed.text,
                        is_recurring=False,
                    )
                    for parsed in parsed_items
                ]
                note = next((parsed.note for parsed in parsed_items if parsed.note), "")
                send_private_msg(context.user_id, build_add_success_message(added_items, note=note))
                context.log("[REMINDER_QUERY] answered_without_ocai=True")
                return SkillResult(handled=True, source=self.name)

            return SkillResult(handled=False, source=self.name, status="ignore")
        except ValueError as exc:
            send_private_msg(context.user_id, str(exc))
            context.log("[REMINDER_QUERY] answered_without_ocai=True")
            return SkillResult(handled=True, source=self.name, status="bad_request")
        except Exception:
            context.log("[REMINDER] handle error")
            traceback.print_exc()
            send_private_msg(context.user_id, "提醒处理失败，请稍后重试。")
            return SkillResult(handled=True, source=self.name, status="error")
