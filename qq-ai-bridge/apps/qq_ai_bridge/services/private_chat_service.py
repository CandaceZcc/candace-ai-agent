"""Private chat orchestration helpers."""

from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR
from storage_utils import get_user_workspace as ensure_user_workspace

from apps.qq_ai_bridge.services.prompt_service import build_private_ai_prompt


def get_user_workspace(user_id):
    """Ensure and return the per-user workspace."""
    return ensure_user_workspace(BASE_DATA_DIR, user_id)


__all__ = ["get_user_workspace", "build_private_ai_prompt"]
