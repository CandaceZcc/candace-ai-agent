"""NapCat HTTP client helpers."""

import asyncio
import json
import random
import re
import time
import traceback

import requests

from apps.qq_ai_bridge.config.settings import NAPCAT_HTTP, NAPCAT_TOKEN
from apps.qq_ai_bridge.services.reply_sanitizer import sanitize_outbound_reply

OUTBOUND_SPLIT_PATTERN = re.compile(r"\n\s*\n+")
OUTBOUND_SPLIT_TOKEN = "[[SEND_SPLIT]]"
OUTBOUND_MAX_PARTS = 5
OUTBOUND_SEND_INTERVAL_SECONDS = 0.35
REACTION_EMOJI_CANDIDATES = {
    # 先尝试 Moonlark/QQ 常见 face id，再回退旧候选。
    # 目标：减少出现“滚木”等非预期表情的概率。
    "laugh_cry": ("182", "264", "128514", "10002"),
    "red_button": ("66", "2764", "10001"),
    "lollipop": ("147", "127853", "10010"),
    "lick_screen": ("214", "128069", "10013"),
}


def _post_json(api_name: str, payload: dict, timeout: int = 15):
    api_url = f"{NAPCAT_HTTP}/{api_name}?access_token={NAPCAT_TOKEN}"
    return requests.post(api_url, json=payload, timeout=timeout)


def _force_split_message(text: str, target_parts: int) -> list[str]:
    """Best-effort split when caller explicitly requires multiple messages."""
    target_parts = max(1, min(target_parts, OUTBOUND_MAX_PARTS))
    text = sanitize_outbound_reply(text)
    if not text or target_parts <= 1:
        return [text] if text else []

    sentence_chunks = [seg.strip() for seg in re.findall(r"[^。！？!?；;]+[。！？!?；;]?", text) if seg.strip()]
    if len(sentence_chunks) >= target_parts:
        grouped: list[str] = []
        for idx in range(target_parts):
            start = (len(sentence_chunks) * idx) // target_parts
            end = (len(sentence_chunks) * (idx + 1)) // target_parts
            piece = "".join(sentence_chunks[start:end]).strip()
            if piece:
                grouped.append(piece)
        if len(grouped) >= target_parts:
            return grouped[:target_parts]

    word_chunks = [seg.strip() for seg in text.split(" ") if seg.strip()]
    if len(word_chunks) >= target_parts:
        grouped = []
        for idx in range(target_parts):
            start = (len(word_chunks) * idx) // target_parts
            end = (len(word_chunks) * (idx + 1)) // target_parts
            piece = " ".join(word_chunks[start:end]).strip()
            if piece:
                grouped.append(piece)
        if len(grouped) >= target_parts:
            return grouped[:target_parts]

    grouped = []
    text_len = len(text)
    for idx in range(target_parts):
        start = (text_len * idx) // target_parts
        end = (text_len * (idx + 1)) // target_parts
        piece = text[start:end].strip()
        if piece:
            grouped.append(piece)
    return grouped[:target_parts] if grouped else [text]


def split_outbound_messages(
    msg: str,
    max_parts: int = OUTBOUND_MAX_PARTS,
    force_parts: int | None = None,
) -> list[str]:
    """Split one model reply into multiple outbound QQ messages."""
    normalized = str(msg or "").replace("\r\n", "\n").replace("\r", "\n")
    normalized = normalized.replace(OUTBOUND_SPLIT_TOKEN, "\n\n")
    raw_parts = OUTBOUND_SPLIT_PATTERN.split(normalized) if normalized else []
    if not raw_parts:
        raw_parts = [normalized]

    parts: list[str] = []
    for raw_part in raw_parts:
        cleaned = sanitize_outbound_reply(raw_part)
        if not cleaned:
            continue
        parts.append(cleaned)
        if len(parts) >= max_parts:
            break

    if force_parts and force_parts > 1 and len(parts) <= 1:
        source_text = parts[0] if parts else normalized
        forced = _force_split_message(source_text, min(force_parts, max_parts))
        if forced:
            return forced
    return parts


def send_private_msg(user_id, msg, quiet: bool = False, force_parts: int | None = None):
    """Send a private message via NapCat."""
    parts = split_outbound_messages(msg, force_parts=force_parts)
    if not parts:
        if not quiet:
            print(f"[SEND_PRIVATE] skip-empty-sanitized user_id={user_id}")
        return {"ok": False, "reason": "empty_message"}

    sent = 0
    last_resp = None
    try:
        for idx, part in enumerate(parts):
            if not quiet:
                print(
                    f"[SEND_PRIVATE] 准备发消息给 {user_id} "
                    f"part={idx + 1}/{len(parts)}: {part[:120]!r}"
                )
            last_resp = _post_json("send_private_msg", {"user_id": user_id, "message": part}, timeout=15)
            if not quiet:
                print(
                    f"[SEND_PRIVATE] NapCat 返回 part={idx + 1}/{len(parts)}: "
                    f"{last_resp.status_code} {last_resp.text}"
                )
            sent += 1
            if idx < len(parts) - 1:
                time.sleep(OUTBOUND_SEND_INTERVAL_SECONDS)
        return {
            "ok": bool(last_resp and last_resp.ok and sent == len(parts)),
            "status_code": getattr(last_resp, "status_code", None),
            "text": getattr(last_resp, "text", ""),
            "parts_sent": sent,
            "parts_total": len(parts),
        }
    except Exception as e:
        if not quiet:
            print(f"[SEND_PRIVATE] 异常: {e}")
            traceback.print_exc()
        return {"ok": False, "error": str(e), "parts_sent": sent, "parts_total": len(parts)}


def _build_group_message_payload(part: str, reply_to_message_id: int | None = None):
    if reply_to_message_id:
        return [
            {"type": "reply", "data": {"id": str(int(reply_to_message_id))}},
            {"type": "text", "data": {"text": part}},
        ]
    return part


def send_group_msg(
    group_id,
    msg,
    quiet: bool = False,
    force_parts: int | None = None,
    reply_to_message_id: int | None = None,
):
    """Send a group message via NapCat."""
    parts = split_outbound_messages(msg, force_parts=force_parts)
    if not parts:
        if not quiet:
            print(f"[SEND_GROUP] skip-empty-sanitized group_id={group_id}")
        return

    sent = 0
    last_resp = None
    try:
        for idx, part in enumerate(parts):
            payload_message = _build_group_message_payload(
                part,
                reply_to_message_id=reply_to_message_id if idx == 0 else None,
            )
            if not quiet:
                print(
                    f"[SEND_GROUP] 准备发群消息到 {group_id} "
                    f"part={idx + 1}/{len(parts)}: {part[:120]!r}"
                    f" reply_to={reply_to_message_id if idx == 0 else None}"
                )
            last_resp = _post_json(
                "send_group_msg",
                {"group_id": group_id, "message": payload_message},
                timeout=15,
            )
            if not quiet:
                print(
                    f"[SEND_GROUP] NapCat 返回 part={idx + 1}/{len(parts)}: "
                    f"{last_resp.status_code} {last_resp.text}"
                )
            sent += 1
            if idx < len(parts) - 1:
                time.sleep(OUTBOUND_SEND_INTERVAL_SECONDS)
        return {
            "ok": bool(last_resp and last_resp.ok and sent == len(parts)),
            "status_code": getattr(last_resp, "status_code", None),
            "text": getattr(last_resp, "text", ""),
            "parts_sent": sent,
            "parts_total": len(parts),
        }
    except Exception as e:
        if not quiet:
            print(f"[SEND_GROUP] 异常: {e}")
            traceback.print_exc()
        return {"ok": False, "error": str(e), "parts_sent": sent, "parts_total": len(parts)}


def set_msg_emoji_like(message_id, emoji_id: str, quiet: bool = False):
    """Set one emoji reaction on a message."""
    try:
        resp = _post_json(
            "set_msg_emoji_like",
            {"message_id": int(message_id), "emoji_id": str(emoji_id)},
            timeout=10,
        )
        ok = bool(resp.ok)
        retcode = None
        text = getattr(resp, "text", "")
        if text:
            try:
                payload = json.loads(text)
                retcode = payload.get("retcode")
                ok = ok and (retcode in (None, 0))
            except Exception:
                pass
        if not quiet:
            print(
                f"[REACTION] set_msg_emoji_like message_id={message_id} "
                f"emoji_id={emoji_id} ok={ok} status={resp.status_code}"
            )
        return {
            "ok": ok,
            "status_code": getattr(resp, "status_code", None),
            "retcode": retcode,
            "text": text,
            "emoji_id": str(emoji_id),
        }
    except Exception as exc:
        if not quiet:
            print(f"[REACTION] set_msg_emoji_like failed message_id={message_id} emoji_id={emoji_id} error={exc}")
        return {"ok": False, "error": str(exc), "emoji_id": str(emoji_id)}


def react_message_with_preferred_emojis(
    message_id,
    quiet: bool = False,
    preferred_order: tuple[str, ...] = ("laugh_cry", "red_button", "lollipop", "lick_screen"),
):
    """Try preferred emoji reactions in rotated order until one succeeds."""
    ordered_names = [name for name in preferred_order if name in REACTION_EMOJI_CANDIDATES]
    if not ordered_names:
        return {"ok": False, "error": "empty_preferred_order"}

    # Use message_id to rotate priorities so successful reactions don't stick to one emoji forever.
    try:
        seed = int(message_id or 0)
    except Exception:
        seed = int(time.time())
    start = abs(seed) % len(ordered_names)
    rotated_names = ordered_names[start:] + ordered_names[:start]

    for name in rotated_names:
        candidate_ids = list(REACTION_EMOJI_CANDIDATES.get(name, ()))
        if len(candidate_ids) > 1:
            # Keep fallback reliability while reducing fixed first-id bias.
            rng = random.Random(f"{seed}:{name}")
            head = candidate_ids[:1]
            tail = candidate_ids[1:]
            rng.shuffle(tail)
            candidate_ids = head + tail
        for emoji_id in candidate_ids:
            result = set_msg_emoji_like(message_id, emoji_id=emoji_id, quiet=quiet)
            if result.get("ok"):
                result["emoji_name"] = name
                return result
    return {"ok": False, "error": "all_emoji_candidates_failed"}


async def send_private_msg_async(user_id, msg, quiet: bool = False):
    """Async wrapper for sending a private message via NapCat."""
    return await asyncio.to_thread(send_private_msg, user_id, msg, quiet, None)


async def send_group_msg_async(group_id, msg, quiet: bool = False):
    """Async wrapper for sending a group message via NapCat."""
    return await asyncio.to_thread(send_group_msg, group_id, msg, quiet, None, None)


def get_forward_msg(forward_id: str):
    """Resolve merged-forward message nodes through NapCat/OneBot."""
    if not forward_id:
        return None
    try:
        resp = _post_json("get_forward_msg", {"message_id": forward_id, "id": forward_id}, timeout=20)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        print(f"[FORWARD] get_forward_msg failed forward_id={forward_id} error={exc}")
        return None


def get_msg_detail(message_id):
    """Fetch message detail by message_id through NapCat."""
    if not message_id:
        return None
    try:
        resp = _post_json("get_msg", {"message_id": int(message_id)}, timeout=15)
        if not resp.ok:
            print(f"[MSG] get_msg failed status={resp.status_code} message_id={message_id}")
            return None
        payload = resp.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if isinstance(data, dict):
            return data
        return None
    except Exception as exc:
        print(f"[MSG] get_msg failed message_id={message_id} error={exc}")
        return None


def fetch_napcat_file_download_info(file_info):
    """Resolve a download URL for a file message through NapCat."""
    file_id = file_info.get("uuid")
    sub_id = file_info.get("sub_id")
    if not file_id:
        reason = "missing_file_id"
        print(f"[FILE_API] 跳过接口调用: {reason}, file_info={file_info}")
        return None, reason

    api_url = f"{NAPCAT_HTTP}/get_file?access_token={NAPCAT_TOKEN}"
    payload = {"file_id": file_id}
    if sub_id:
        payload["sub_id"] = sub_id

    print(f"[FILE_API] 请求接口: {api_url}, payload={payload}")

    try:
        resp = requests.post(api_url, json=payload, timeout=15)
        resp.raise_for_status()
        result = resp.json()
    except Exception as e:
        reason = f"request_failed: {e}"
        print(f"[FILE_API] 接口调用失败: {reason}")
        return None, reason

    data = result.get("data", {}) if isinstance(result, dict) else {}
    resolved_url = None
    if isinstance(data, dict):
        resolved_url = (
            data.get("url")
            or data.get("download_url")
            or data.get("file_url")
            or data.get("fileUrl")
        )

    print(
        "[FILE_API] 接口返回关键字段: "
        f"url={data.get('url') if isinstance(data, dict) else None!r}, "
        f"download_url={data.get('download_url') if isinstance(data, dict) else None!r}, "
        f"file_url={data.get('file_url') if isinstance(data, dict) else None!r}"
    )

    if resolved_url:
        return resolved_url, "resolved_by_get_file"

    reason = "no_download_url_in_response"
    print(f"[FILE_API] 未解析到下载地址: {reason}, response={result}")
    return None, reason
