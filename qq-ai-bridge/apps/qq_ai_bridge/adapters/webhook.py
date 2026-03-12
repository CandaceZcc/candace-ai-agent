"""Webhook adapter for NapCat/QQ incoming events."""

from flask import jsonify, request

from apps.qq_ai_bridge.adapters.message_parser import (
    extract_text_and_mention,
    normalize_query_text,
)
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR
from apps.qq_ai_bridge.services.file_service import extract_file_info
from apps.qq_ai_bridge.services.group_chat_service import load_group_config, should_log_group
from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.skills.registry import build_skill_registry
from apps.qq_ai_bridge.skills.router import dispatch_skill
from image_utils import extract_image_inputs
from storage_utils import (
    append_group_chat_log,
    append_style_sample as append_group_style_sample,
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
        normalized_msg = normalize_query_text(msg)
        image_inputs = extract_image_inputs(data)
        file_info = extract_file_info(data)

        webhook_log("[WEBHOOK] message_type:", message_type)
        webhook_log("[WEBHOOK] 原始提取文本:", repr(msg))
        webhook_log("[WEBHOOK] 规范化后文本:", repr(normalized_msg))
        webhook_log("[WEBHOOK] mentioned_self:", mentioned_self)
        webhook_log("[WEBHOOK] image_inputs:", image_inputs)
        webhook_log("[WEBHOOK] 文件信息:", file_info)

        if message_type == "group":
            if not group_config:
                group_config = load_group_config(group_id)
            webhook_log("[WEBHOOK] group_config:", group_config)

            if normalized_msg:
                if group_config.get("capture_all_messages", False):
                    append_group_chat_log(
                        BASE_DATA_DIR,
                        group_id,
                        {"timestamp": int(data.get("time") or 0), "user_id": user_id, "message": normalized_msg},
                        limit=500,
                    )
                if group_config.get("learn_style", False):
                    append_group_style_sample(
                        BASE_DATA_DIR, group_id, user_id, normalized_msg, timestamp=int(data.get("time") or 0)
                    )

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

        webhook_log(f"[ROUTE] 未处理的 message_type: {message_type}")
        return "ignore"

    return webhook
