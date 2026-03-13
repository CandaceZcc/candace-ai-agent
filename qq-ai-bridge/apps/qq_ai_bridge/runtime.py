"""Transitional orchestration layer for the QQ AI bridge."""

import os
import re
from pathlib import Path

from flask import Flask
from dotenv import load_dotenv


def _load_runtime_env() -> None:
    bridge_root = Path(__file__).resolve().parents[2]
    repo_root = bridge_root.parent
    env_candidates = (
        ("bridge", bridge_root / ".env"),
        ("repo", repo_root / ".env"),
    )

    print(
        "[SYSTEM] env search order: "
        + " -> ".join(f"{label}:{path}" for label, path in env_candidates)
    )
    loaded_any = False
    for label, dotenv_path in env_candidates:
        if not dotenv_path.exists():
            print(f"[SYSTEM] env file missing: {label}:{dotenv_path}")
            continue

        loaded = load_dotenv(dotenv_path=dotenv_path, override=False)
        status = "loaded" if loaded else "present but no new values applied"
        print(f"[SYSTEM] env file {status}: {label}:{dotenv_path}")
        loaded_any = loaded_any or loaded

    if not loaded_any:
        print("[SYSTEM] no .env values loaded, using process env only")


_load_runtime_env()

from apps.qq_ai_bridge.adapters.webhook import register_routes
from apps.qq_ai_bridge.config.settings import (
    AGENT_SYSTEM_PROMPT,
    AI_CMD,
    ALLOWED_ACTIONS,
    ALLOWED_PRIVATE_USER,
    BASE_DATA_DIR,
    CONFIG_DIR,
    GROUP_CONFIG_PATH,
    GROUP_DATA_DIR,
    GROUP_UPLOAD_DIR,
    IMAGE_TMP_DIR,
    MAX_FILE_CONTENT_LEN,
    MAX_REPLY_LEN,
    NAPCAT_HTTP,
    NAPCAT_TOKEN,
    OFFICE_XML_EXTS,
    OWNER_QQ,
    OWNER_NAME,
    PC_AGENT_URL,
    PRIVATE_UPLOAD_DIR,
    PRIVATE_USERS_DIR,
    REMINDERS_PATH,
    SCHEDULE_PATH,
    SCHEDULER_STATE_PATH,
    TEXT_LIKE_EXTS,
)
from apps.qq_ai_bridge.services.agent_service import (
    agent_llm_plan,
    call_agent_llm,
    call_pc_agent_api,
    execute_agent_plan,
    execute_agent_workflow,
    get_agent_session,
    handle_pc_agent_command,
    observe_screen_text,
    reset_agent_session,
    summarize_agent_issue,
)
from apps.qq_ai_bridge.services.file_service import (
    build_binary_file_summary,
    describe_fs_entry,
    download_file_if_possible,
    extract_docx_text,
    extract_file_content_for_ai,
    extract_file_info,
    extract_pdf_text,
    extract_pptx_text,
    extract_xlsx_text,
    extract_zip_summary,
    handle_file_message,
    read_text_file,
    resolve_file_download_info,
    safe_filename,
)
from apps.qq_ai_bridge.services.group_chat_service import load_group_config, should_log_group
from apps.qq_ai_bridge.services.private_chat_service import build_private_ai_prompt, get_user_workspace
from apps.qq_ai_bridge.services.prompt_service import build_group_safe_prompt, build_vision_user_text, load_group_soul
from apps.qq_ai_bridge.services.scheduler import start_scheduler
from apps.qq_ai_bridge.services.vision_service import log_vision_config_status, run_vision_pipeline
from apps.qq_ai_bridge.adapters.message_parser import extract_text_and_mention, has_meaningful_text, normalize_query_text
from apps.qq_ai_bridge.adapters.napcat_client import (
    fetch_napcat_file_download_info,
    send_group_msg as _send_group_msg_raw,
    send_private_msg as _send_private_msg_raw,
)
from shared.ai.llm_client import call_ai


app = Flask(__name__)


def trim_reply(text: str) -> str:
    """Trim a reply to the configured max length."""
    text = (text or "").strip()
    if not text:
        return "（空回复）"
    return text[:MAX_REPLY_LEN]


def normalize_reply(text: str, max_len: int = 80) -> str:
    """Force a single-line compact reply."""
    text = (text or "").replace("\r", " ").replace("\n", " ")
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) > max_len:
        text = text[:max_len].rstrip("，。！？,.!?:：； ")
    return text or "（空回复）"


def sanitize_for_group(text: str) -> str:
    """Filter sensitive patterns before sending group replies."""
    ip_pattern = r"\b(?:[0-9]{1,3}\.){3}[0-9]{1,3}\b"
    text = re.sub(ip_pattern, "[IP已隐藏]", text)

    path_pattern = r"(/home/\S+|/root/\S+|/var/\S+|/etc/\S+|/usr/\S+|/opt/\S+|/tmp/\S+|C:\\[^\s]+|\\[^\s]+)"
    text = re.sub(path_pattern, "[路径]", text)

    token_pattern = r"(api[_-]?key|token|secret|password)[\"']?\s*[:=]\s*[\"']?\S+[\"']?"
    text = re.sub(token_pattern, "[密钥]", text, flags=re.IGNORECASE)
    return text


def send_private_msg(user_id, msg):
    """Compatibility wrapper that normalizes private replies before sending."""
    _send_private_msg_raw(user_id, normalize_reply(trim_reply(msg), max_len=MAX_REPLY_LEN))


def send_group_msg(group_id, msg, quiet: bool = False):
    """Compatibility wrapper that normalizes group replies before sending."""
    msg = trim_reply(msg)
    msg = sanitize_for_group(msg)
    msg = normalize_reply(msg, max_len=MAX_REPLY_LEN)
    _send_group_msg_raw(group_id, msg, quiet=quiet)


log_vision_config_status(print)

for path in (
    PRIVATE_UPLOAD_DIR,
    GROUP_UPLOAD_DIR,
    PRIVATE_USERS_DIR,
    GROUP_DATA_DIR,
    CONFIG_DIR,
    IMAGE_TMP_DIR,
    BASE_DATA_DIR,
):
    os.makedirs(path, exist_ok=True)


register_routes(app)
start_scheduler()


__all__ = [
    "app",
    "NAPCAT_HTTP",
    "NAPCAT_TOKEN",
    "ALLOWED_PRIVATE_USER",
    "OWNER_NAME",
    "OWNER_QQ",
    "AI_CMD",
    "MAX_REPLY_LEN",
    "MAX_FILE_CONTENT_LEN",
    "BASE_DATA_DIR",
    "PRIVATE_UPLOAD_DIR",
    "GROUP_UPLOAD_DIR",
    "PRIVATE_USERS_DIR",
    "GROUP_DATA_DIR",
    "GROUP_CONFIG_PATH",
    "IMAGE_TMP_DIR",
    "REMINDERS_PATH",
    "SCHEDULER_STATE_PATH",
    "SCHEDULE_PATH",
    "TEXT_LIKE_EXTS",
    "OFFICE_XML_EXTS",
    "PC_AGENT_URL",
    "ALLOWED_ACTIONS",
    "AGENT_SYSTEM_PROMPT",
    "safe_filename",
    "trim_reply",
    "normalize_reply",
    "sanitize_for_group",
    "load_group_config",
    "should_log_group",
    "get_user_workspace",
    "build_private_ai_prompt",
    "build_vision_user_text",
    "run_vision_pipeline",
    "send_private_msg",
    "send_group_msg",
    "call_ai",
    "call_pc_agent_api",
    "get_agent_session",
    "reset_agent_session",
    "observe_screen_text",
    "call_agent_llm",
    "agent_llm_plan",
    "execute_agent_plan",
    "summarize_agent_issue",
    "execute_agent_workflow",
    "handle_pc_agent_command",
    "normalize_query_text",
    "has_meaningful_text",
    "extract_text_and_mention",
    "extract_file_info",
    "fetch_napcat_file_download_info",
    "resolve_file_download_info",
    "download_file_if_possible",
    "read_text_file",
    "extract_pdf_text",
    "extract_docx_text",
    "extract_pptx_text",
    "extract_xlsx_text",
    "extract_zip_summary",
    "build_binary_file_summary",
    "describe_fs_entry",
    "extract_file_content_for_ai",
    "load_group_soul",
    "build_group_safe_prompt",
    "handle_file_message",
]
