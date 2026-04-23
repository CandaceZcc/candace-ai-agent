"""Early gate filters for low-value or disabled inbound events."""

from __future__ import annotations

from dataclasses import dataclass

from storage_utils import is_group_whitelisted

from apps.qq_ai_bridge.config.settings import GROUP_CONFIG_PATH


@dataclass
class EarlyGateResult:
    """Result of early-gate filtering."""

    dropped: bool
    reason: str = ""


def gate_raw_event(data: dict, log=print) -> EarlyGateResult:
    """Drop raw webhook events before deeper parsing when possible."""
    post_type = str(data.get("post_type") or "")
    if post_type == "notice":
        log("[EARLY_GATE] drop reason=notice_event")
        return EarlyGateResult(dropped=True, reason="notice_event")
    if post_type != "message":
        log(f"[EARLY_GATE] drop reason=unsupported_post_type post_type={post_type or 'unknown'}")
        return EarlyGateResult(dropped=True, reason="unsupported_post_type")

    group_id = data.get("group_id")
    if group_id and not is_group_whitelisted(GROUP_CONFIG_PATH, group_id):
        log(f"[EARLY_GATE] drop reason=disabled_group group_id={group_id}")
        return EarlyGateResult(dropped=True, reason="disabled_group")

    sender = data.get("sender", {}) if isinstance(data.get("sender"), dict) else {}
    user_id = data.get("user_id") or sender.get("user_id")
    self_id = data.get("self_id")
    if self_id and user_id and str(self_id) == str(user_id):
        log(f"[EARLY_GATE] drop reason=self_message group_id={group_id} user_id={user_id}")
        return EarlyGateResult(dropped=True, reason="self_message")

    return EarlyGateResult(dropped=False)


def gate_parsed_event(parsed_data: dict, log=print) -> EarlyGateResult:
    """Drop already parsed events using text/image/file signals."""
    if not parsed_data:
        log("[EARLY_GATE] drop reason=empty_payload")
        return EarlyGateResult(dropped=True, reason="empty_payload")

    if parsed_data.get("type") == "file":
        return EarlyGateResult(dropped=False)

    text = str(parsed_data.get("text") or "").strip()
    has_image = bool((parsed_data.get("image_inputs") or {}).get("has_image"))
    if not text and not has_image:
        log(
            f"[EARLY_GATE] drop reason=empty_message group_id={parsed_data.get('group_id')} "
            f"user_id={parsed_data.get('user_id')}"
        )
        return EarlyGateResult(dropped=True, reason="empty_message")

    return EarlyGateResult(dropped=False)

