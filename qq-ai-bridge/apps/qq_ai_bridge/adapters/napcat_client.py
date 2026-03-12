"""NapCat HTTP client helpers."""

import requests

from apps.qq_ai_bridge.config.settings import NAPCAT_HTTP, NAPCAT_TOKEN
from apps.qq_ai_bridge.services.reply_sanitizer import sanitize_outbound_reply


def _post_json(api_name: str, payload: dict, timeout: int = 15):
    api_url = f"{NAPCAT_HTTP}/{api_name}?access_token={NAPCAT_TOKEN}"
    return requests.post(api_url, json=payload, timeout=timeout)


def send_private_msg(user_id, msg, quiet: bool = False):
    """Send a private message via NapCat."""
    msg = sanitize_outbound_reply(msg)
    if not msg:
        if not quiet:
            print(f"[SEND_PRIVATE] skip-empty-sanitized user_id={user_id}")
        return
    if not quiet:
        print(f"[SEND_PRIVATE] 准备发消息给 {user_id}: {msg[:120]!r}")

    try:
        resp = _post_json("send_private_msg", {"user_id": user_id, "message": msg}, timeout=15)
        if not quiet:
            print(f"[SEND_PRIVATE] NapCat 返回: {resp.status_code} {resp.text}")
    except Exception as e:
        if not quiet:
            print(f"[SEND_PRIVATE] 异常: {e}")


def send_group_msg(group_id, msg, quiet: bool = False):
    """Send a group message via NapCat."""
    msg = sanitize_outbound_reply(msg)
    if not msg:
        if not quiet:
            print(f"[SEND_GROUP] skip-empty-sanitized group_id={group_id}")
        return
    if not quiet:
        print(f"[SEND_GROUP] 准备发群消息到 {group_id}: {msg[:120]!r}")

    try:
        resp = _post_json("send_group_msg", {"group_id": group_id, "message": msg}, timeout=15)
        if not quiet:
            print(f"[SEND_GROUP] NapCat 返回: {resp.status_code} {resp.text}")
    except Exception as e:
        if not quiet:
            print(f"[SEND_GROUP] 异常: {e}")


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
