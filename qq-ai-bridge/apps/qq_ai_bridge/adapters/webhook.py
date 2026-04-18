import traceback

from flask import Blueprint, jsonify, request

from apps.qq_ai_bridge.adapters.message_parser import extract_text_and_mention, normalize_query_text
from apps.qq_ai_bridge.runtime import (
    _send_group_msg_raw,
    _send_private_msg_raw,
)
from apps.qq_ai_bridge.services.file_service import handle_file_message
from apps.qq_ai_bridge.services.group_chat_service import load_group_config, should_log_group
from apps.qq_ai_bridge.services.style_service import capture_group_style
from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.skills.registry import build_skill_registry
from apps.qq_ai_bridge.skills.router import dispatch_skill

webhook_bp = Blueprint("webhook", __name__)
SKILL_REGISTRY = build_skill_registry()


class MessageParser:
    """Helper class to parse incoming webhook message data."""

    @staticmethod
    def parse_common_data(data: dict) -> dict:
        msg_type = data.get("message_type")
        sender = data.get("sender", {})
        user_id = data.get("user_id") or sender.get("user_id")

        group_id = data.get("group_id")
        raw_message = str(data.get("message", "") or data.get("raw_message", ""))

        if msg_type == "group":
            nick = (
                sender.get("card")
                or sender.get("nickname")
                or sender.get("nick")
                or sender.get("remark")
                or str(user_id)
            )
        else:
            nick = sender.get("nickname") or sender.get("nick") or sender.get("remark") or str(user_id)

        file_info = extract_file_info(data)
        if file_info:
            return {
                "type": "file",
                "msg_type": msg_type,
                "user_id": user_id,
                "group_id": group_id,
                "file_info": file_info,
                "raw_message": raw_message,
                "nick": nick,
            }

        text, is_mentioned = extract_text_and_mention(raw_message, data)
        return {
            "type": "text",
            "msg_type": msg_type,
            "user_id": user_id,
            "group_id": group_id,
            "text": text,
            "is_mentioned": is_mentioned,
            "raw_message": raw_message,
            "nick": nick,
            "timestamp": data.get("time"),
        }


def extract_file_info(data: dict) -> dict | None:
    message_chain = data.get("message", [])
    if isinstance(message_chain, list):
        for elem in message_chain:
            if elem.get("type") == "file":
                file_elem = elem.get("data", {})
                return {
                    "name": file_elem.get("fileName") or file_elem.get("name"),
                    "url": (
                        file_elem.get("downloadUrl")
                        or file_elem.get("url")
                        or file_elem.get("fileUrl")
                    ),
                    "size": file_elem.get("fileSize"),
                    "uuid": file_elem.get("fileUuid") or file_elem.get("fileId"),
                    "base64": file_elem.get("base64"),
                }
    return None


class SkillDispatcher:
    @staticmethod
    def dispatch(parsed_data: dict) -> None:
        if parsed_data["type"] == "file":
            handle_file_message(
                parsed_data["msg_type"],
                parsed_data["user_id"],
                parsed_data["group_id"],
                parsed_data["file_info"],
            )
            return

        msg_type = parsed_data["msg_type"]
        user_id = parsed_data["user_id"]
        group_id = parsed_data["group_id"]
        text = parsed_data["text"]
        is_mentioned = parsed_data["is_mentioned"]
        raw_message = parsed_data["raw_message"]

        effective_text = normalize_query_text(text)
        is_private = msg_type == "private"
        is_group = msg_type == "group"

        group_config = {}
        should_log = True

        if is_group and group_id:
            group_config = load_group_config(group_id)
            should_log = should_log_group(group_id)
            if group_config.get("learn_style", False):
                capture_group_style("data", group_id, user_id, effective_text, log=print)

        context = SkillContext(
            raw_message=raw_message,
            effective_text=effective_text,
            is_private=is_private,
            is_group=is_group,
            user_id=user_id,
            group_id=group_id,
            mentioned_self=is_mentioned,
            group_config=group_config,
            should_log=should_log,
            timestamp=parsed_data.get("timestamp"),
        )

        result = dispatch_skill(context, SKILL_REGISTRY)
        if result and result.response_text:
            if is_private:
                _send_private_msg_raw(user_id, result.response_text)
            elif is_group:
                _send_group_msg_raw(group_id, result.response_text)


@webhook_bp.route("/qq-webhook", methods=["POST"])
def qq_webhook():
    data = request.json or {}
    post_type = data.get("post_type")

    if post_type == "message":
        try:
            parsed = MessageParser.parse_common_data(data)
            if parsed:
                SkillDispatcher.dispatch(parsed)
        except Exception as e:
            print(f"[WEBHOOK] Exception during message processing: {e}")
            traceback.print_exc()

    elif post_type == "notice":
        notice_type = data.get("notice_type")
        sub_type = data.get("sub_type")
        if notice_type == "group_upload" and sub_type == "file":
            try:
                group_id = data.get("group_id")
                user_id = data.get("user_id")
                file_info = data.get("file", {})
                if file_info:
                    handle_file_message("group", user_id, group_id, file_info)
            except Exception as e:
                print(f"[WEBHOOK] Exception during file upload notice processing: {e}")
                traceback.print_exc()
        else:
            print(f"[WEBHOOK] notice received: {notice_type} {sub_type}")

    return jsonify({"status": "ok"})


def register_routes(app):
    app.register_blueprint(webhook_bp)
