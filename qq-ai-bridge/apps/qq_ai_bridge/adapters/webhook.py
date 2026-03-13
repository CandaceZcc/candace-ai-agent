"""Webhook adapter for NapCat/QQ incoming events."""

from flask import jsonify, request

from apps.qq_ai_bridge.adapters.message_parser import (
    extract_text_and_mention,
    extract_forward_id,
    format_forward_messages,
    normalize_query_text,
)
from apps.qq_ai_bridge.adapters.napcat_client import get_forward_msg
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR
from apps.qq_ai_bridge.services.file_service import extract_file_info
from apps.qq_ai_bridge.services.group_chat_service import load_group_config, should_log_group
from apps.qq_ai_bridge.services.style_service import capture_group_style
from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.skills.chat import ChatSkill
from apps.qq_ai_bridge.skills.registry import build_skill_registry
from apps.qq_ai_bridge.skills.router import dispatch_skill
from image_utils import extract_image_inputs
from storage_utils import (
    append_group_chat_log,
)


def register_routes(app):
    """Register webhook routes on the Flask app."""
    skill_registry = build_skill_registry()

    @app.route("/", methods=["POST"])
    def webhook():
        data = request.json
        if not data:
            print("[WEBHOOK] 空请求")
            return "ok"

        post_type = data.get("post_type")
        message_type = data.get("message_type", "")
        group_id = data.get("group_id", 0)
        group_config = None
        should_log = True

        if post_type == "message" and message_type == "group":
            group_config = load_group_config(group_id)
            should_log = should_log_group(group_id)
            if group_config.get("ignore", False):
                return jsonify({"status": "ignored_group"})

        if should_log:
            print("[WEBHOOK] 收到请求:", data)

        def webhook_log(*args):
            if should_log:
                print(*args)

        if post_type != "message":
            webhook_log(f"[WEBHOOK] 忽略非消息事件: {post_type}")
            return "ignore"

        user_id = data.get("user_id")
        self_id = data.get("self_id")

        msg, mentioned_self = extract_text_and_mention(data, self_id)
        forward_text = _resolve_forward_text(data, webhook_log)
        if forward_text:
            msg = "\n".join(part for part in (msg, forward_text) if part).strip()
        normalized_msg = normalize_query_text(msg)
        image_inputs = extract_image_inputs(data)
        image_text = normalize_query_text(image_inputs.get("text", ""))
        effective_text = _select_effective_text(forward_text, normalized_msg, image_text)
        file_info = extract_file_info(data)

        webhook_log("[WEBHOOK] message_type:", message_type)
        webhook_log("[WEBHOOK] 原始提取文本:", repr(msg))
        webhook_log("[WEBHOOK] 规范化后文本:", repr(normalized_msg))
        webhook_log("[FORWARD] final_text_selected:", repr(effective_text))
        if forward_text:
            webhook_log("[FORWARD] expanded_text:", repr(forward_text[:500]))
        webhook_log("[WEBHOOK] mentioned_self:", mentioned_self)
        webhook_log("[WEBHOOK] image_inputs:", image_inputs)
        if image_inputs.get("has_image"):
            webhook_log("[VISION] image detected in webhook")
            webhook_log("[VISION] image URLs extracted:", image_inputs.get("image_urls", []))
        webhook_log("[WEBHOOK] 文件信息:", file_info)

        if message_type == "group":
            if not group_config:
                group_config = load_group_config(group_id)
            webhook_log("[WEBHOOK] group_config:", group_config)
            sender_name = _extract_sender_name(data, user_id)

            if effective_text:
                if group_config.get("capture_all_messages", False):
                    append_group_chat_log(
                        BASE_DATA_DIR,
                        group_id,
                        {
                            "timestamp": int(data.get("time") or 0),
                            "user_id": user_id,
                            "sender_name": sender_name,
                            "message": effective_text,
                        },
                        limit=500,
                    )
                if group_config.get("learn_style", False):
                    capture_group_style(BASE_DATA_DIR, group_id, user_id, effective_text, log=webhook_log)

        context = SkillContext(
            data=data,
            post_type=post_type,
            message_type=message_type,
            user_id=user_id,
            self_id=self_id,
            group_id=group_id,
            group_config=group_config or {},
            should_log=should_log,
            msg=msg,
            normalized_msg=normalized_msg,
            effective_text=effective_text,
            mentioned_self=mentioned_self,
            image_inputs=image_inputs,
            file_info=file_info,
            logger=webhook_log,
            timestamp=int(data.get("time") or 0),
        )

        result = dispatch_skill(context, skill_registry)
        if result and result.handled:
            if result.status == "ignore":
                return "ignore"
            payload = result.response_payload or {"status": result.status or "ok"}
            if result.source and "source" not in payload:
                payload["source"] = result.source
            return jsonify(payload)

        # Temporary safety net: if a normal private text falls through,
        # force it to chat skill to avoid silent no-reply behavior.
        if (
            message_type == "private"
            and effective_text
            and not image_inputs.get("has_image")
            and not file_info
        ):
            webhook_log("[SKILL] fallback -> chat (private normal text)")
            fallback = ChatSkill().handle(context)
            response_produced = bool(fallback.response_payload or fallback.response_text)
            webhook_log(
                f"[SKILL] fallback result chat handled={fallback.handled} status={fallback.status} response_produced={response_produced}"
            )
            if fallback.handled:
                if fallback.status == "ignore":
                    return "ignore"
                payload = fallback.response_payload or {"status": fallback.status or "ok"}
                if fallback.source and "source" not in payload:
                    payload["source"] = fallback.source
                return jsonify(payload)

        webhook_log(f"[ROUTE] 未处理的 message_type: {message_type}")
        return "ignore"

    return webhook


def _resolve_forward_text(data: dict, logger) -> str:
    forward_id = extract_forward_id(data)
    if not forward_id:
        return ""
    logger(f"[FORWARD] detected forward_id={forward_id}")
    payload = get_forward_msg(forward_id)
    if not payload:
        logger(f"[FORWARD] failed to expand forward_id={forward_id}")
        return ""
    try:
        text = format_forward_messages(payload)
    except Exception as exc:
        logger(f"[FORWARD] format failed forward_id={forward_id} error={exc}")
        return ""
    if not text:
        logger(f"[FORWARD] empty content forward_id={forward_id}")
        return ""
    logger(f"[FORWARD] expanded forward_id={forward_id} chars={len(text)}")
    return text


def _select_effective_text(forward_text: str, normalized_text: str, image_text: str) -> str:
    for candidate in (forward_text, normalized_text, image_text):
        normalized = normalize_query_text(candidate)
        if normalized:
            return normalized
    return ""


def _extract_sender_name(data: dict, user_id) -> str:
    sender = data.get("sender", {}) if isinstance(data, dict) else {}
    if isinstance(sender, dict):
        for key in ("card", "nickname", "nick", "remark"):
            value = sender.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return str(user_id or "?")
