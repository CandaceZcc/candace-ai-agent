import datetime
from typing import Any, List

from apps.qq_ai_bridge.services.reminder_store import ReminderStore


class ReminderService:
    """Manages the parsing, creation, and retrieval of reminders."""

    def __init__(self, store: ReminderStore):
        self.store = store

    def process_add_reminder(self, user_id: int, reminder_text: str, trigger_at: datetime.datetime) -> dict[str, Any]:
        """
        Process the addition of a reminder for a specific user.

        Args:
            user_id: The ID of the user.
            reminder_text: The text content of the reminder.
            trigger_at: The time the reminder should trigger.

        Returns:
            The reminder response payload.
        """
        try:
            return self.store.add_reminder(user_id, trigger_at, reminder_text)
        except KeyError as e:
            return {"status": "error", "message": f"创建提醒失败：缺少必填字段 {e}"}

    def delete_reminder(self, user_id: int, reminder_id: int) -> bool:
        """
        Delete a reminder.

        Args:
            user_id: The user ID.
            reminder_id: The ID of the reminder to delete.

        Returns:
            True if deleted successfully, False otherwise.
        """
        return self.store.cancel_reminder(reminder_id, user_id=user_id) is not None

    def list_reminders(self, user_id: int) -> List[dict[str, Any]]:
        """
        List all pending reminders for a user.

        Args:
            user_id: The user ID.

        Returns:
            A list of reminder payloads.
        """
        try:
            return self.store.list_pending(user_id)
        except Exception as e:
            print(f"[REMINDER] Failed to list reminders: {e}")
            return []
