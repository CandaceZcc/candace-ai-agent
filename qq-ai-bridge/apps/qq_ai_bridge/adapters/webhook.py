import asyncio
import traceback

from flask import Blueprint, jsonify, request

from apps.qq_ai_bridge.adapters.message_parser import extract_text_and_mention, normalize_query_text
from apps.qq_ai_bridge.runtime import (
    _send_group_msg_raw,
    _send_private_msg_raw,
)
from apps.qq_ai_bridge.config.settings import (
    VOCAT_API_TOKEN,
    VOCAT_BOT_ID,
    VOCAT_DEVICE_NAME,
    VOCAT_EXPRESSION_API_URL,
    VOCAT_INSTANCE_ID,
    VOCAT_PRODUCT_KEY,
    VOCAT_TTS_API_URL,
    VOCAT_WEBHOOK_TOKEN,
)
from apps.qq_ai_bridge.services.file_service import handle_file_message
from apps.qq_ai_bridge.services.group_chat_service import load_group_config, should_log_group
from apps.qq_ai_bridge.services.style_service import capture_group_style
from apps.qq_ai_bridge.services.vocat_service import (
    maybe_handle_vocat_remote_command,
    process_vocat_query,
)
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
        self_id = data.get("self_id")
        user_id = data.get("user_id") or sender.get("user_id")

        group_id = data.get("group_id")
        raw_message = data.get("message")
        if raw_message is None or raw_message == "":
            raw_message = data.get("raw_message", "")
        raw_message_text = str(raw_message)

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
                "raw_message": raw_message_text,
                "nick": nick,
            }

        text, is_mentioned = extract_text_and_mention(data, self_id)
        return {
            "type": "text",
            "msg_type": msg_type,
            "user_id": user_id,
            "group_id": group_id,
            "text": text,
            "is_mentioned": is_mentioned,
            "raw_message": raw_message_text,
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
            data={},
            post_type="message",
            message_type=msg_type,
            user_id=user_id,
            self_id=None,
            group_id=group_id,
            group_config=group_config,
            should_log=should_log,
            msg=text,
            normalized_msg=effective_text,
            effective_text=effective_text,
            mentioned_self=is_mentioned,
            image_inputs={},
            file_info=None,
            logger=print,
            timestamp=parsed_data.get("timestamp"),
            nick=parsed_data.get("nick", ""),
            raw_message=raw_message,
        )

        result = dispatch_skill(context, SKILL_REGISTRY)
        if result and result.response_text:
            if is_private:
                _send_private_msg_raw(user_id, result.response_text)
            elif is_group:
                _send_group_msg_raw(group_id, result.response_text)


def _run_async(coro):
    return asyncio.run(coro)


def _preview_text(text: str, limit: int = 80) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


@webhook_bp.route("/", methods=["POST"])
@webhook_bp.route("/qq-webhook", methods=["POST"])
def qq_webhook():
    data = request.json or {}
    post_type = data.get("post_type")

    if post_type == "message":
        try:
            parsed = MessageParser.parse_common_data(data)
            if parsed:
                if parsed.get("type") == "text":
                    preview = _preview_text(parsed.get("text", ""))
                    if parsed.get("msg_type") == "private":
                        print(
                            f"[WEBHOOK] recv private user_id={parsed.get('user_id')} "
                            f"nick={parsed.get('nick')!r} text={preview!r}"
                        )
                    elif parsed.get("msg_type") == "group":
                        print(
                            f"[WEBHOOK] recv group group_id={parsed.get('group_id')} "
                            f"user_id={parsed.get('user_id')} nick={parsed.get('nick')!r} text={preview!r}"
                        )
                elif parsed.get("type") == "file":
                    print(
                        f"[WEBHOOK] recv file msg_type={parsed.get('msg_type')} "
                        f"user_id={parsed.get('user_id')} group_id={parsed.get('group_id')} "
                        f"name={parsed.get('file_info', {}).get('name')!r}"
                    )
                if parsed.get("type") == "text" and parsed.get("msg_type") == "private":
                    remote_result = _run_async(
                        maybe_handle_vocat_remote_command(parsed.get("user_id"), parsed.get("text", ""))
                    )
                    if remote_result and remote_result.get("handled"):
                        _send_private_msg_raw(parsed.get("user_id"), remote_result.get("reply", "已执行。"))
                        return jsonify({"status": "ok", "source": "vocat_remote_control"})
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


@webhook_bp.route("/vocat/webhook", methods=["GET", "POST"])
def vocat_webhook():
    """Handle VoCat hardware webhook requests."""
    if request.method == "GET":
        ready_for_inbound = True
        ready_for_remote_control = all(
            (
                VOCAT_EXPRESSION_API_URL,
                VOCAT_TTS_API_URL,
                any((VOCAT_INSTANCE_ID, VOCAT_PRODUCT_KEY, VOCAT_DEVICE_NAME, VOCAT_BOT_ID)),
            )
        )
        return jsonify(
            {
                "ok": True,
                "service": "vocat_webhook",
                "ready_for_inbound": ready_for_inbound,
                "ready_for_remote_control": ready_for_remote_control,
                "config": {
                    "webhook_token_configured": bool(VOCAT_WEBHOOK_TOKEN),
                    "api_token_configured": bool(VOCAT_API_TOKEN),
                    "expression_api_configured": bool(VOCAT_EXPRESSION_API_URL),
                    "tts_api_configured": bool(VOCAT_TTS_API_URL),
                    "instance_id_configured": bool(VOCAT_INSTANCE_ID),
                    "product_key_configured": bool(VOCAT_PRODUCT_KEY),
                    "device_name_configured": bool(VOCAT_DEVICE_NAME),
                    "bot_id_configured": bool(VOCAT_BOT_ID),
                },
            }
        )

    data = request.get_json(silent=True) or {}
    print(
        f"[VOCAT] recv query={_preview_text(data.get('query') or data.get('text') or data.get('message') or '')!r} "
        f"keys={sorted(data.keys())}"
    )
    if VOCAT_WEBHOOK_TOKEN:
        request_token = (
            request.headers.get("X-Vocat-Token")
            or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
            or str(data.get("token", "")).strip()
        )
        if request_token != VOCAT_WEBHOOK_TOKEN:
            return jsonify({"ok": False, "error": "unauthorized"}), 401
    try:
        result = _run_async(process_vocat_query(data))
        return jsonify(result)
    except Exception as exc:
        print(f"[VOCAT] webhook processing failed: {exc}")
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


def register_routes(app):
    app.register_blueprint(webhook_bp)
