import json
import os
import random
import re
import tempfile
import threading
import time


_GROUP_CHAT_LOG_LOCKS: dict[str, threading.Lock] = {}
_GROUP_CHAT_LOG_LOCKS_GUARD = threading.Lock()
_SECRET_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b(api[\s_-]?key|access[\s_-]?token|secret[\s_-]?key|password|密码|密钥)\s*[:=]?\s*"
    r"(sk-[A-Za-z0-9_-]{8,}|[A-Za-z0-9_./+=-]{8,})"
)
_OPENAI_STYLE_KEY_PATTERN = re.compile(r"\bsk-[A-Za-z0-9_-]{8,}\b")

DEFAULT_GROUP_CONFIG = {
    "default": {
        "capture_all_messages": False,
        "bot_can_reply": True,
        "learn_style": False,
        "reply_all_messages": False,
        "enable_vision": True,
        "follow_group_reactions": False,
        "reaction_follow_probability": 0.5,
        "reaction_notice_log": False,
        "ignore": False,
        "mute_log": False
    }
}


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def ensure_json_file(path: str, default_data):
    ensure_dir(os.path.dirname(path))
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(default_data, f, ensure_ascii=False, indent=2)


def ensure_text_file(path: str):
    ensure_dir(os.path.dirname(path))
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            f.write("")


def load_json_file(path: str, default_data):
    ensure_json_file(path, default_data)
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default_data


def save_json_file(path: str, data):
    """通过同目录原子替换保存 JSON，避免读到半写文件。"""
    ensure_dir(os.path.dirname(path))
    fd, temp_path = tempfile.mkstemp(prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.unlink(temp_path)


def redact_sensitive_text(text: str) -> str:
    """遮蔽消息中的凭据值，同时保留普通 token 概念讨论。"""
    value = str(text or "")
    value = _SECRET_ASSIGNMENT_PATTERN.sub(
        lambda match: f"{match.group(1)}{'=' if match.group(1).isascii() else ''}[REDACTED]",
        value,
    )
    return _OPENAI_STYLE_KEY_PATTERN.sub("[REDACTED]", value)


def read_text_file(path: str) -> str:
    ensure_text_file(path)
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def trim_text_file_lines(path: str, max_lines: int):
    ensure_text_file(path)
    with open(path, "r", encoding="utf-8") as f:
        lines = f.readlines()
    if len(lines) <= max_lines:
        return
    with open(path, "w", encoding="utf-8") as f:
        f.writelines(lines[-max_lines:])


def append_text_line(path: str, line: str, max_lines: int):
    ensure_text_file(path)
    with open(path, "a", encoding="utf-8") as f:
        f.write(line.rstrip("\n") + "\n")
    trim_text_file_lines(path, max_lines=max_lines)


def get_user_workspace(base_dir: str, user_id) -> dict:
    user_dir = os.path.join(base_dir, "private_users", str(user_id))
    ensure_dir(user_dir)

    history_path = os.path.join(user_dir, "history.json")
    memory_path = os.path.join(user_dir, "memory.txt")
    style_path = os.path.join(user_dir, "style_samples.txt")
    profile_path = os.path.join(user_dir, "profile.json")

    ensure_json_file(history_path, [])
    ensure_text_file(memory_path)
    ensure_text_file(style_path)
    ensure_json_file(profile_path, {})

    return {
        "dir": user_dir,
        "history_path": history_path,
        "memory_path": memory_path,
        "style_samples_path": style_path,
        "profile_path": profile_path,
    }


def append_private_history(
    base_dir: str,
    user_id,
    user_text: str,
    bot_reply: str,
    limit: int = 20,
    user_timestamp: int | None = None,
    assistant_timestamp: int | None = None,
):
    workspace = get_user_workspace(base_dir, user_id)
    history = load_json_file(workspace["history_path"], [])
    user_ts = int(user_timestamp or time.time())
    assistant_ts = int(assistant_timestamp or time.time())
    history.append({
        "timestamp": assistant_ts,
        "user_timestamp": user_ts,
        "assistant_timestamp": assistant_ts,
        "last_activity_timestamp": max(user_ts, assistant_ts),
        "user": user_text,
        "assistant": bot_reply
    })
    save_json_file(workspace["history_path"], history[-limit:])


def append_private_style_sample(base_dir: str, user_id, message: str, timestamp=None, max_lines: int = 5000):
    workspace = get_user_workspace(base_dir, user_id)
    ts = int(timestamp or time.time())
    append_text_line(
        workspace["style_samples_path"],
        f"{ts} | {user_id} | {message}",
        max_lines=max_lines
    )


def load_private_context(base_dir: str, user_id) -> dict:
    workspace = get_user_workspace(base_dir, user_id)
    return {
        "workspace": workspace,
        "history": load_json_file(workspace["history_path"], []),
        "memory": read_text_file(workspace["memory_path"]).strip(),
        "style_samples_path": workspace["style_samples_path"],
        "profile": load_json_file(workspace["profile_path"], {}),
    }


def ensure_group_config_file(config_path: str):
    ensure_json_file(config_path, DEFAULT_GROUP_CONFIG)


def load_group_config_store(config_path: str) -> dict:
    ensure_group_config_file(config_path)
    data = load_json_file(config_path, DEFAULT_GROUP_CONFIG)
    if not isinstance(data, dict):
        return DEFAULT_GROUP_CONFIG.copy()

    default_cfg = data.get("default", {})
    if not isinstance(default_cfg, dict):
        default_cfg = {}

    normalized = {"default": {**DEFAULT_GROUP_CONFIG["default"], **default_cfg}}
    for key, value in data.items():
        if key == "default" or not isinstance(value, dict):
            continue
        normalized[str(key)] = value.copy()
    return normalized


def load_group_config(config_path: str, group_id) -> dict:
    data = load_group_config_store(config_path)
    default_cfg = data.get("default", DEFAULT_GROUP_CONFIG["default"]).copy()
    group_cfg = data.get(str(group_id), {})
    merged = default_cfg.copy()
    if isinstance(group_cfg, dict):
        merged.update(group_cfg)
    return merged


def is_group_whitelisted(config_path: str, group_id) -> bool:
    data = load_group_config_store(config_path)
    key = str(group_id)
    if key not in data:
        return False
    group_cfg = data.get(key, {})
    if not isinstance(group_cfg, dict):
        return False
    return bool(group_cfg.get("enabled", False)) and not bool(group_cfg.get("ignore", False))


def save_group_config_store(config_path: str, data: dict):
    normalized = load_group_config_store(config_path)
    default_cfg = data.get("default", {}) if isinstance(data, dict) else {}
    if isinstance(default_cfg, dict):
        normalized["default"] = {**DEFAULT_GROUP_CONFIG["default"], **default_cfg}

    explicit_groups = {}
    if isinstance(data, dict):
        for key, value in data.items():
            if key == "default" or not isinstance(value, dict):
                continue
            explicit_groups[str(key)] = value

    normalized = {"default": normalized["default"], **explicit_groups}
    save_json_file(config_path, normalized)


def get_group_workspace(base_dir: str, group_id) -> dict:
    group_dir = os.path.join(base_dir, "groups", str(group_id))
    ensure_dir(group_dir)

    chat_log_path = os.path.join(group_dir, "chat_log.json")
    style_path = os.path.join(group_dir, "style_samples.txt")
    style_profiles_dir = os.path.join(group_dir, "style_profiles")
    ensure_dir(style_profiles_dir)
    style_group_profile_path = os.path.join(style_profiles_dir, "group_style.json")

    ensure_json_file(chat_log_path, [])
    ensure_text_file(style_path)

    return {
        "dir": group_dir,
        "chat_log_path": chat_log_path,
        "style_samples_path": style_path,
        "style_profiles_dir": style_profiles_dir,
        "style_group_profile_path": style_group_profile_path,
        "style_user_profile_path": lambda user_id: os.path.join(style_profiles_dir, f"user_{user_id}.json"),
    }


def _get_group_chat_log_lock(path: str) -> threading.Lock:
    """为每个群聊日志文件复用一把锁，避免并发追加互相覆盖。"""
    with _GROUP_CHAT_LOG_LOCKS_GUARD:
        lock = _GROUP_CHAT_LOG_LOCKS.get(path)
        if lock is None:
            lock = threading.Lock()
            _GROUP_CHAT_LOG_LOCKS[path] = lock
        return lock


def append_group_chat_log(base_dir: str, group_id, message_entry: dict, limit: int = 500):
    """追加群聊事件；同一消息的角色事件再次到达时更新较完整内容。"""
    workspace = get_group_workspace(base_dir, group_id)
    chat_log_path = workspace["chat_log_path"]
    with _get_group_chat_log_lock(chat_log_path):
        chat_log = load_json_file(chat_log_path, [])
        role = str(message_entry.get("role") or "").strip()
        message_id = message_entry.get("message_id")
        source = str(message_entry.get("source") or "").strip()
        replaced = False
        if role and message_id is not None:
            for index in range(len(chat_log) - 1, -1, -1):
                existing = chat_log[index]
                if not isinstance(existing, dict):
                    continue
                if (
                    str(existing.get("role") or "").strip() == role
                    and existing.get("message_id") == message_id
                    and str(existing.get("source") or "").strip() == source
                ):
                    chat_log[index] = {**existing, **message_entry}
                    replaced = True
                    break
        if not replaced:
            chat_log.append(message_entry)
        save_json_file(chat_log_path, chat_log[-limit:])


def append_style_sample(base_dir: str, group_id, user_id, message: str, timestamp=None, max_lines: int = 5000):
    workspace = get_group_workspace(base_dir, group_id)
    ts = int(timestamp or time.time())
    append_text_line(
        workspace["style_samples_path"],
        f"{ts} | {user_id} | {message}",
        max_lines=max_lines
    )


def sample_style_lines(style_path: str, sample_size: int = 10):
    ensure_text_file(style_path)
    with open(style_path, "r", encoding="utf-8") as f:
        lines = [line.strip() for line in f if line.strip()]

    if not lines:
        return []
    if len(lines) <= sample_size:
        return lines
    return random.sample(lines, sample_size)
