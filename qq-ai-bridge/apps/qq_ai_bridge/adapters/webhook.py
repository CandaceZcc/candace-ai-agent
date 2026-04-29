import asyncio
import traceback
import threading
import time
from datetime import datetime, timezone

from flask import Blueprint, jsonify, request

from apps.qq_ai_bridge.adapters.message_parser import (
    extract_at_targets,
    extract_forward_id,
    extract_reply_reference,
    extract_text_and_mention,
    format_forward_messages,
    normalize_query_text,
)
from apps.qq_ai_bridge.adapters.napcat_client import (
    get_forward_msg,
    send_group_msg as _send_group_msg_raw,
    send_private_msg as _send_private_msg_raw,
)
from apps.qq_ai_bridge.config.settings import (
    VOCAT_API_TOKEN,
    VOCAT_BOT_ID,
    VOCAT_DEVICE_NAME,
    VOCAT_DAILY_BROADCAST_TO_DEVICE,
    VOCAT_EXPRESSION_API_URL,
    VOCAT_INSTANCE_ID,
    VOCAT_PRODUCT_KEY,
    VOCAT_QQ_REPLY_TO_DEVICE,
    VOCAT_REMOTE_CONTROL_USERS,
    VOCAT_TTS_API_URL,
    VOCAT_TRUSTED_DEVICE_IPS,
    VOCAT_WEBHOOK_TOKEN,
)
from apps.qq_ai_bridge.services.file_service import (
    extract_file_info as extract_uploaded_file_info,
    handle_file_message,
)
from apps.qq_ai_bridge.services.group_chat_service import load_group_config, should_log_group
from apps.qq_ai_bridge.services.reaction_follow_service import (
    handle_group_reaction_notice,
    record_group_message_for_reaction_learning,
)
from apps.qq_ai_bridge.services.style_service import capture_group_style
from apps.qq_ai_bridge.services.vocat_service import (
    maybe_handle_vocat_remote_command,
    process_vocat_query,
)
from apps.qq_ai_bridge.services.vocat_command_queue import (
    ack_vocat_command,
    enqueue_vocat_expression,
    enqueue_vocat_tts,
    get_vocat_queue_status,
    get_vocat_runtime_status,
    poll_vocat_command,
    record_vocat_ack,
    record_vocat_poll,
    record_vocat_webhook,
)
from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.skills.registry import build_skill_registry
from apps.qq_ai_bridge.skills.router import dispatch_skill
from storage_utils import is_group_whitelisted
from apps.qq_ai_bridge.config.settings import GROUP_CONFIG_PATH

webhook_bp = Blueprint("webhook", __name__)
SKILL_REGISTRY = build_skill_registry()
_LAST_VOCAT_POST: dict | None = None
_PENDING_IMAGE_CAPTIONS: dict[str, dict] = {}
_PENDING_IMAGE_CAPTIONS_LOCK = threading.Lock()
IMAGE_CAPTION_GRACE_SECONDS = 5.0


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

        file_info = extract_uploaded_file_info(data)
        if file_info:
            file_info = file_info.copy()
            file_info["message_id"] = data.get("message_id")
            return {
                "type": "file",
                "msg_type": msg_type,
                "user_id": user_id,
                "group_id": group_id,
                "file_info": file_info,
                "raw_message": raw_message_text,
                "nick": nick,
                "message_id": data.get("message_id"),
            }

        text, is_mentioned = extract_text_and_mention(data, self_id)
        image_inputs = extract_image_inputs(data, text)
        reply_reference = extract_reply_reference(data)
        at_targets = extract_at_targets(data)
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
            "image_inputs": image_inputs,
            "reply_reference": reply_reference,
            "at_targets": at_targets,
            "self_id": self_id,
            "message_id": data.get("message_id"),
        }


def extract_image_inputs(data: dict, text: str) -> dict:
    """Extract image URLs from OneBot/NapCat payloads."""
    image_urls: list[str] = []
    dropped_image_urls: list[str] = []
    resolved_relative_urls: list[str] = []

    def _collect_url(raw_url) -> None:
        url = normalize_query_text(str(raw_url or ""))
        if not url:
            return
        if url.startswith("http://") or url.startswith("https://"):
            image_urls.append(url)
            return
        if url.startswith("//"):
            resolved = "https:" + url
            image_urls.append(resolved)
            resolved_relative_urls.append(resolved)
            return
        dropped_image_urls.append(url)

    message_chain = data.get("message", [])
    if isinstance(message_chain, list):
        for elem in message_chain:
            if not isinstance(elem, dict):
                continue
            elem_type = str(elem.get("type", "")).lower()
            payload = elem.get("data", {}) if isinstance(elem.get("data"), dict) else {}
            if elem_type not in {"image", "img", "photo", "pic"}:
                continue
            for key in ("url", "file", "downloadUrl", "image_url", "originUrl", "src"):
                _collect_url(payload.get(key))

    elements = data.get("elements", [])
    if isinstance(elements, list):
        for elem in elements:
            if not isinstance(elem, dict):
                continue
            pic_elem = elem.get("picElement")
            if isinstance(pic_elem, dict):
                for key in ("sourcePath", "sourceUrl", "url", "md5"):
                    _collect_url(pic_elem.get(key))
            image_elem = elem.get("imageElement")
            if isinstance(image_elem, dict):
                for key in ("url", "sourceUrl", "originUrl", "downloadUrl"):
                    _collect_url(image_elem.get(key))

    deduped_urls = []
    seen = set()
    for url in image_urls:
        if url in seen:
            continue
        seen.add(url)
        deduped_urls.append(url)

    return {
        "has_image": bool(deduped_urls),
        "image_urls": deduped_urls,
        "text": normalize_query_text(text),
        "dropped_image_urls": dropped_image_urls,
        "resolved_relative_urls": resolved_relative_urls,
    }
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
            if bool(group_config.get("ignore", False)) or not bool(group_config.get("enabled", True)):
                print(f"[ROUTE] group ignored by config group_id={group_id} enabled={group_config.get('enabled', True)}")
                return
            should_log = should_log_group(group_id)
            if group_config.get("learn_style", False):
                capture_group_style("data", group_id, user_id, effective_text, log=print)

        context = SkillContext(
            data=parsed_data,
            post_type="message",
            message_type=msg_type,
            user_id=user_id,
            self_id=parsed_data.get("self_id"),
            group_id=group_id,
            group_config=group_config,
            should_log=should_log,
            msg=text,
            normalized_msg=effective_text,
            effective_text=effective_text,
            mentioned_self=is_mentioned,
            image_inputs=parsed_data.get("image_inputs", {}),
            file_info=None,
            logger=print,
            timestamp=parsed_data.get("timestamp"),
            message_id=parsed_data.get("message_id"),
            nick=parsed_data.get("nick", ""),
            raw_message=raw_message,
        )

        result = dispatch_skill(context, SKILL_REGISTRY)
        if result and result.response_text:
            if is_private:
                _send_private_msg_raw(user_id, result.response_text)
                queue_result = _maybe_enqueue_private_reply_to_vocat(user_id, result.response_text)
                if queue_result:
                    print(
                        f"[VOCAT] queued private reply command_id={queue_result.get('command_id')} "
                        f"user_id={user_id}"
                    )
            elif is_group:
                _send_group_msg_raw(group_id, result.response_text)


def _caption_pending_key(parsed_data: dict) -> str:
    return f"{parsed_data.get('msg_type')}:{parsed_data.get('group_id') or ''}:{parsed_data.get('user_id') or ''}"


def _maybe_handle_image_caption_merge(parsed_data: dict) -> bool:
    if parsed_data.get("type") != "text" or parsed_data.get("msg_type") != "group":
        return False
    image_inputs = parsed_data.get("image_inputs") or {}
    has_image = bool(image_inputs.get("has_image"))
    text = normalize_query_text(parsed_data.get("text", ""))
    key = _caption_pending_key(parsed_data)

    if has_image and not text:
        with _PENDING_IMAGE_CAPTIONS_LOCK:
            _PENDING_IMAGE_CAPTIONS[key] = {"parsed": parsed_data, "created_at": time.time()}
        timer = threading.Timer(IMAGE_CAPTION_GRACE_SECONDS, _flush_pending_image_caption, args=(key,))
        timer.daemon = True
        timer.start()
        print(
            f"[VISION] waiting_for_caption group_id={parsed_data.get('group_id')}"
            f" user_id={parsed_data.get('user_id')} grace_seconds={IMAGE_CAPTION_GRACE_SECONDS}"
        )
        return True

    if text and not has_image:
        with _PENDING_IMAGE_CAPTIONS_LOCK:
            pending = _PENDING_IMAGE_CAPTIONS.pop(key, None)
        if pending and time.time() - float(pending.get("created_at", 0)) <= IMAGE_CAPTION_GRACE_SECONDS + 0.5:
            merged = dict(pending["parsed"])
            merged["text"] = text
            merged["raw_message"] = f"{pending['parsed'].get('raw_message', '')} {parsed_data.get('raw_message', '')}".strip()
            image_inputs = dict(merged.get("image_inputs") or {})
            image_inputs["text"] = text
            merged["image_inputs"] = image_inputs
            print(
                f"[VISION] merged_followup_caption group_id={merged.get('group_id')}"
                f" user_id={merged.get('user_id')} text={_preview_text(text)!r}"
            )
            SkillDispatcher.dispatch(merged)
            return True
    return False


def _flush_pending_image_caption(key: str) -> None:
    with _PENDING_IMAGE_CAPTIONS_LOCK:
        pending = _PENDING_IMAGE_CAPTIONS.pop(key, None)
    if not pending:
        return
    parsed = pending.get("parsed") or {}
    print(
        f"[VISION] caption_wait_timeout group_id={parsed.get('group_id')}"
        f" user_id={parsed.get('user_id')}"
    )
    SkillDispatcher.dispatch(parsed)


def _run_async(coro):
    return asyncio.run(coro)


def _preview_text(text: str, limit: int = 80) -> str:
    normalized = " ".join(str(text or "").split())
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _authorized_vocat_request() -> tuple[bool, tuple[dict, int] | None]:
    remote_addr = request.remote_addr or ""
    if remote_addr in {"127.0.0.1", "::1", "localhost"} or remote_addr in VOCAT_TRUSTED_DEVICE_IPS:
        return True, None
    if not VOCAT_WEBHOOK_TOKEN:
        return True, None
    request_token = (
        request.headers.get("X-Vocat-Token")
        or request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
        or str(request.values.get("token", "")).strip()
        or str((request.get_json(silent=True) or {}).get("token", "")).strip()
    )
    if request_token != VOCAT_WEBHOOK_TOKEN:
        return False, ({"ok": False, "error": "unauthorized"}, 401)
    return True, None


def _maybe_enqueue_private_reply_to_vocat(user_id, reply: str) -> dict | None:
    if not VOCAT_QQ_REPLY_TO_DEVICE:
        return None
    try:
        user_id_int = int(user_id)
    except (TypeError, ValueError):
        return None
    if user_id_int not in VOCAT_REMOTE_CONTROL_USERS:
        return None
    return enqueue_vocat_tts(reply, source="qq_private_reply")


def _should_handle_group_file_notice(group_id, group_config: dict | None) -> bool:
    return False


def _attach_forward_text_if_present(raw_event: dict, parsed: dict) -> dict:
    if parsed.get("type") != "text":
        return parsed
    forward_id = extract_forward_id(raw_event)
    forward_payload = get_forward_msg(forward_id) if forward_id else raw_event
    forward_text = format_forward_messages(forward_payload)
    if not forward_text:
        return parsed
    merged = dict(parsed)
    prefix = normalize_query_text(merged.get("text", ""))
    merged_text = f"{prefix}\n[聊天记录]\n{forward_text}" if prefix else f"[聊天记录]\n{forward_text}"
    merged["text"] = merged_text
    merged["raw_message"] = f"{merged.get('raw_message', '')}\n{merged_text}".strip()
    image_inputs = dict(merged.get("image_inputs") or {})
    image_inputs["text"] = merged_text
    merged["image_inputs"] = image_inputs
    print(
        f"[WEBHOOK] merged forward chat record forward_id={forward_id or '-'}"
        f" chars={len(forward_text)}"
    )
    return merged


@webhook_bp.route("/", methods=["POST"])
@webhook_bp.route("/qq-webhook", methods=["POST"])
def qq_webhook():
    data = request.json or {}
    post_type = data.get("post_type")

    if post_type == "message":
        try:
            parsed = MessageParser.parse_common_data(data)
            if parsed:
                parsed = _attach_forward_text_if_present(data, parsed)
                if parsed.get("msg_type") == "group" and not is_group_whitelisted(GROUP_CONFIG_PATH, parsed.get("group_id")):
                    return jsonify({"status": "ok", "skipped": "group_not_whitelisted"})
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
                        record_group_message_for_reaction_learning(
                            group_id=parsed.get("group_id"),
                            message_id=parsed.get("message_id"),
                            user_id=parsed.get("user_id"),
                            sender_name=parsed.get("nick", ""),
                            text=parsed.get("text", ""),
                            raw_message=parsed.get("raw_message", ""),
                            timestamp=parsed.get("timestamp"),
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
                if not _maybe_handle_image_caption_merge(parsed):
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
                group_config = load_group_config(group_id) if group_id else {}
                if file_info and _should_handle_group_file_notice(group_id, group_config):
                    handle_file_message("group", user_id, group_id, file_info)
                elif file_info:
                    print(f"[WEBHOOK] group file ignored group_id={group_id} reason=group_file_disabled")
            except Exception as e:
                print(f"[WEBHOOK] Exception during file upload notice processing: {e}")
                traceback.print_exc()
        elif notice_type == "group_msg_emoji_like":
            try:
                group_id = data.get("group_id") or data.get("groupId")
                group_config = load_group_config(group_id) if group_id else {}
                result = handle_group_reaction_notice(data, group_config=group_config, self_id=data.get("self_id"), log=print)
                print(
                    f"[WEBHOOK] reaction notice handled={result.get('handled')} followed={result.get('followed')} "
                    f"group_id={result.get('group_id')} message_id={result.get('message_id')} emoji_id={result.get('emoji_id')} "
                    f"reason={result.get('reason', '')}"
                )
            except Exception as e:
                print(f"[WEBHOOK] Exception during reaction notice processing: {e}")
                traceback.print_exc()
        else:
            print(f"[WEBHOOK] notice received: {notice_type} {sub_type}")

    return jsonify({"status": "ok"})


@webhook_bp.route("/vocat/webhook", methods=["GET", "POST"])
def vocat_webhook():
    """Handle VoCat hardware webhook requests."""
    global _LAST_VOCAT_POST
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
                "last_vocat_post": _LAST_VOCAT_POST,
                "config": {
                    "webhook_token_configured": bool(VOCAT_WEBHOOK_TOKEN),
                    "api_token_configured": bool(VOCAT_API_TOKEN),
                    "expression_api_configured": bool(VOCAT_EXPRESSION_API_URL),
                    "tts_api_configured": bool(VOCAT_TTS_API_URL),
                    "poll_control_enabled": True,
                    "qq_reply_to_device": bool(VOCAT_QQ_REPLY_TO_DEVICE),
                    "daily_broadcast_to_device": bool(VOCAT_DAILY_BROADCAST_TO_DEVICE),
                    "instance_id_configured": bool(VOCAT_INSTANCE_ID),
                    "product_key_configured": bool(VOCAT_PRODUCT_KEY),
                    "device_name_configured": bool(VOCAT_DEVICE_NAME),
                    "bot_id_configured": bool(VOCAT_BOT_ID),
                },
            }
        )

    data = request.get_json(silent=True) or {}
    remote_addr = request.remote_addr or "unknown"
    query_preview = _preview_text(data.get("query") or data.get("text") or data.get("message") or "")
    _LAST_VOCAT_POST = {
        "at": datetime.now(timezone.utc).isoformat(),
        "remote_addr": remote_addr,
        "is_local_request": remote_addr in {"127.0.0.1", "::1", "localhost"},
        "query_preview": query_preview,
    }
    print(
        f"[VOCAT] recv remote_addr={remote_addr} query={query_preview!r} "
        f"keys={sorted(data.keys())}"
    )
    authorized, error_response = _authorized_vocat_request()
    if not authorized:
        payload, status = error_response
        return jsonify(payload), status
    try:
        result = _run_async(process_vocat_query(data))
        record_vocat_webhook(
            query=data.get("query") or data.get("text") or data.get("message") or "",
            reply=result.get("reply", ""),
            expression=result.get("expression"),
            source=result.get("source", ""),
            remote_addr=remote_addr,
        )
        return jsonify(result)
    except Exception as exc:
        print(f"[VOCAT] webhook processing failed: {exc}")
        traceback.print_exc()
        return jsonify({"ok": False, "error": str(exc)}), 500


@webhook_bp.route("/vocat/poll", methods=["GET"])
def vocat_poll():
    """Return the next queued local command for a VoCat device."""
    authorized, error_response = _authorized_vocat_request()
    if not authorized:
        payload, status = error_response
        return jsonify(payload), status

    device_name = request.args.get("device_name") or request.args.get("device") or ""
    command = poll_vocat_command(device_name)
    queue_size = get_vocat_queue_status()["queue_size"]
    record_vocat_poll(command=command, queue_size=queue_size)
    if not command:
        return jsonify({"ok": True, "has_command": False, "queue": queue_size})
    print(
        f"[VOCAT] poll deliver command_id={command.get('id')} type={command.get('type')} "
        f"source={command.get('source', '')}"
    )
    return jsonify({"ok": True, "has_command": True, "command": command})


@webhook_bp.route("/vocat/ack", methods=["POST"])
def vocat_ack():
    """Acknowledge a delivered VoCat command."""
    authorized, error_response = _authorized_vocat_request()
    if not authorized:
        payload, status = error_response
        return jsonify(payload), status

    data = request.get_json(silent=True) or {}
    command_id = data.get("command_id") or data.get("id") or request.values.get("command_id")
    result = ack_vocat_command(str(command_id or ""))
    record_vocat_ack(str(command_id or ""), result)
    print(f"[VOCAT] ack command_id={command_id} result={result}")
    return jsonify(result)


@webhook_bp.route("/vocat/queue", methods=["GET", "POST"])
def vocat_queue_status():
    """Inspect or enqueue VoCat commands."""
    authorized, error_response = _authorized_vocat_request()
    if not authorized:
        payload, status = error_response
        return jsonify(payload), status
    if request.method == "POST":
        data = request.get_json(silent=True) or {}
        command_type = str(data.get("type") or "tts").strip().lower()
        if command_type == "expression":
            result = enqueue_vocat_expression(data.get("expression") or data.get("expression_id") or "happy", source="manual_queue")
        else:
            result = enqueue_vocat_tts(
                str(data.get("text") or data.get("message") or ""),
                source=str(data.get("source") or "manual_queue"),
                expression=data.get("expression"),
            )
        return jsonify(result)
    return jsonify(get_vocat_queue_status())


@webhook_bp.route("/vocat/status", methods=["GET"])
def vocat_status():
    """Return VoCat pull-control runtime status."""
    authorized, error_response = _authorized_vocat_request()
    if not authorized:
        payload, status = error_response
        return jsonify(payload), status
    return jsonify(get_vocat_runtime_status())


def register_routes(app):
    app.register_blueprint(webhook_bp)
