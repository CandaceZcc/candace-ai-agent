import json
import os
import random
import time


DEFAULT_GROUP_CONFIG = {
    "default": {
        "capture_all_messages": False,
        "bot_can_reply": True,
        "learn_style": False,
        "reply_all_messages": False,
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
    ensure_dir(os.path.dirname(path))
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


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

    ensure_json_file(history_path, [])
    ensure_text_file(memory_path)
    ensure_text_file(style_path)

    return {
        "dir": user_dir,
        "history_path": history_path,
        "memory_path": memory_path,
        "style_samples_path": style_path
    }


def append_private_history(base_dir: str, user_id, user_text: str, bot_reply: str, limit: int = 20):
    workspace = get_user_workspace(base_dir, user_id)
    history = load_json_file(workspace["history_path"], [])
    history.append({
        "timestamp": int(time.time()),
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
        "style_samples_path": workspace["style_samples_path"]
    }


def ensure_group_config_file(config_path: str):
    ensure_json_file(config_path, DEFAULT_GROUP_CONFIG)


def load_group_config(config_path: str, group_id) -> dict:
    ensure_group_config_file(config_path)
    data = load_json_file(config_path, DEFAULT_GROUP_CONFIG)
    default_cfg = data.get("default", DEFAULT_GROUP_CONFIG["default"]).copy()
    group_cfg = data.get(str(group_id), {})
    merged = default_cfg.copy()
    if isinstance(group_cfg, dict):
        merged.update(group_cfg)
    return merged


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


def append_group_chat_log(base_dir: str, group_id, message_entry: dict, limit: int = 500):
    workspace = get_group_workspace(base_dir, group_id)
    chat_log = load_json_file(workspace["chat_log_path"], [])
    chat_log.append(message_entry)
    save_json_file(workspace["chat_log_path"], chat_log[-limit:])


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
