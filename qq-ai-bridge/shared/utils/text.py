"""Text utility compatibility wrapper."""

from apps.qq_ai_bridge.runtime import normalize_query_text, normalize_reply, sanitize_for_group, trim_reply

__all__ = ["normalize_query_text", "normalize_reply", "sanitize_for_group", "trim_reply"]
