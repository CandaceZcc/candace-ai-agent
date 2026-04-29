"""Admin UI routes for the QQ AI Bridge console."""

from __future__ import annotations

import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
from flask import Blueprint, jsonify, render_template, request

from storage_utils import load_group_config_store, save_group_config_store

from apps.qq_ai_bridge.config.settings import (
    GROUP_CONFIG_PATH,
    NAPCAT_HTTP,
    NAPCAT_TOKEN,
    OWNER_QQ,
    QQ_AI_BRIDGE_ROOT,
    REPO_ROOT,
    VOCAT_WEBHOOK_TOKEN,
)
from apps.qq_ai_bridge.services.vocat_command_queue import (
    get_vocat_queue_status,
    get_vocat_runtime_status,
)
from apps.qq_ai_bridge.services.group_strategy import DEFAULT_GROUP_STRATEGY, normalize_group_strategy_config
from apps.qq_ai_bridge.services.trace_store import get_trace, list_traces

admin_ui_bp = Blueprint("admin_ui", __name__)
BRIDGE_LOG_PATH = (REPO_ROOT / ".runtime" / "logs" / "bridge.log").resolve()
MAX_LOG_LIMIT = 1000
DEFAULT_LOG_LIMIT = 300
LOG_CATEGORIES = {
    "all",
    "system",
    "group",
    "private",
    "vocat",
    "scheduler",
    "skill",
    "vision",
    "reaction",
    "llm",
    "napcat",
}

_EDITABLE_GROUP_FIELDS = (
    "capture_all_messages",
    "bot_can_reply",
    "learn_style",
    "reply_all_messages",
    "enable_vision",
    "ignore",
    "mute_log",
)
_REACTION_DECISION_MODES = {"llm_first", "hybrid", "rule_first"}
_STRATEGY_PROBABILITY_FIELDS = ("reply_probability", "silence_probability", "reaction_probability")
_STRATEGY_INT_FIELDS = ("delay_min_ms", "delay_max_ms", "context_window_sec", "cooldown_sec")
_SENSITIVE_ASSIGNMENT_PATTERN = re.compile(
    r"(?i)\b("
    r"token|api[_-]?key|authorization|vocat_webhook_token|kimi_api_key|"
    r"openrouter_api_key|moonshot_api_key|access_token"
    r")\b([\"']?\s*[:=]\s*[\"']?)([^\"'\s,&}]+)"
)
_BEARER_PATTERN = re.compile(r"(?i)\b(bearer)\s+([A-Za-z0-9._~+\-/=]+)")
_FIELD_PATTERNS: dict[str, re.Pattern[str]] = {
    "group_id": re.compile(r"\bgroup_id['\"]?\s*[=:]\s*['\"]?([^'\",\s}]+)"),
    "user_id": re.compile(r"\buser_id['\"]?\s*[=:]\s*['\"]?([^'\",\s}]+)"),
    "nick": re.compile(r"\bnick['\"]?\s*[=:]\s*['\"]([^'\"]*)"),
    "text": re.compile(r"\btext['\"]?\s*[=:]\s*['\"]([^'\"]*)"),
    "query": re.compile(r"\bquery['\"]?\s*[=:]\s*['\"]([^'\"]*)"),
    "command_id": re.compile(r"\bcommand_id['\"]?\s*[=:]\s*['\"]?([^'\",\s}]+)"),
    "queue_size": re.compile(r"\bqueue(?:_size)?['\"]?\s*[=:]\s*['\"]?(\d+)"),
    "duration_ms": re.compile(r"\bduration_ms['\"]?\s*[=:]\s*['\"]?(\d+)"),
    "status": re.compile(r"\bstatus['\"]?\s*[=:]\s*['\"]?([^'\",\s}]+)"),
    "retcode": re.compile(r"\bretcode['\"]?\s*[=:]\s*['\"]?(-?\d+)"),
}


def _serialize_group_store() -> dict:
    store = load_group_config_store(GROUP_CONFIG_PATH)
    groups = []
    for group_id, raw in store.items():
        if group_id == "default" or not isinstance(raw, dict):
            continue
        item = raw.copy()
        item["group_id"] = group_id
        item["name"] = str(item.get("name", "") or "")
        item["enabled"] = bool(item.get("enabled", False)) and not bool(item.get("ignore", False))
        item["reply_all_messages"] = bool(item.get("reply_all_messages", False))
        item["trigger_mode"] = "all" if item["reply_all_messages"] else "mention"
        mode = str(item.get("reaction_decision_mode", "llm_first") or "llm_first").strip().lower()
        item["reaction_decision_mode"] = mode if mode in _REACTION_DECISION_MODES else "llm_first"
        item["strategy"] = normalize_group_strategy_config(item)
        groups.append(item)

    groups.sort(key=lambda item: (not item.get("enabled", True), item.get("name") or item["group_id"]))
    default_cfg = (store.get("default", {}) if isinstance(store.get("default"), dict) else {}).copy()
    default_cfg["trigger_mode"] = "all" if default_cfg.get("reply_all_messages", False) else "mention"
    return {
        "groups": groups,
        "default": default_cfg,
        "meta": {
            "config_path": GROUP_CONFIG_PATH,
            "whitelist_count": sum(1 for item in groups if item.get("enabled", True)),
            "total_count": len(groups),
        },
    }


def _normalize_group_payload(raw: dict, existing: dict) -> tuple[str, dict]:
    group_id = str(raw.get("group_id", "")).strip()
    if not group_id or not group_id.isdigit():
        raise ValueError("group_id 必须是纯数字")

    merged = existing.copy()
    merged["name"] = str(raw.get("name", merged.get("name", "")) or "").strip()
    merged["enabled"] = bool(raw.get("enabled", merged.get("enabled", True)))
    if merged["enabled"]:
        merged["ignore"] = False

    trigger_mode = str(raw.get("trigger_mode", "") or "").strip().lower()
    if trigger_mode in {"all", "mention"}:
        merged["reply_all_messages"] = trigger_mode == "all"
    elif "reply_all_messages" in raw:
        merged["reply_all_messages"] = bool(raw.get("reply_all_messages"))

    reaction_mode = str(raw.get("reaction_decision_mode", merged.get("reaction_decision_mode", "llm_first")) or "llm_first")
    reaction_mode = reaction_mode.strip().lower()
    merged["reaction_decision_mode"] = reaction_mode if reaction_mode in _REACTION_DECISION_MODES else "llm_first"
    merged["strategy"] = _normalize_strategy_payload(raw.get("strategy", raw.get("strategy_config", merged.get("strategy", merged.get("strategy_config", {})))))
    merged.pop("strategy_config", None)

    for field in _EDITABLE_GROUP_FIELDS:
        if field in raw and field != "reply_all_messages":
            merged[field] = bool(raw.get(field))

    return group_id, merged


def _normalize_strategy_payload(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    strategy = DEFAULT_GROUP_STRATEGY.copy()
    for field in _STRATEGY_PROBABILITY_FIELDS:
        if field not in raw:
            continue
        try:
            value = float(raw.get(field))
        except (TypeError, ValueError):
            raise ValueError(f"{field} 必须是数字")
        if value < 0 or value > 1:
            raise ValueError(f"{field} 必须在 0 到 1 之间")
        strategy[field] = value
    for field in _STRATEGY_INT_FIELDS:
        if field not in raw:
            continue
        try:
            value = int(raw.get(field))
        except (TypeError, ValueError):
            raise ValueError(f"{field} 必须是整数")
        minimum = 0 if field in {"delay_min_ms", "delay_max_ms", "cooldown_sec"} else 1
        maximum = 60000 if field in {"delay_min_ms", "delay_max_ms"} else 3600
        if field == "context_window_sec":
            maximum = 60
        if value < minimum or value > maximum:
            raise ValueError(f"{field} 必须在 {minimum} 到 {maximum} 之间")
        strategy[field] = value
    strategy["require_mention_for_reply"] = bool(raw.get("require_mention_for_reply", strategy["require_mention_for_reply"]))
    if strategy["delay_max_ms"] < strategy["delay_min_ms"]:
        raise ValueError("delay_max_ms 必须大于等于 delay_min_ms")
    if sum(float(strategy[field]) for field in _STRATEGY_PROBABILITY_FIELDS) <= 0:
        raise ValueError("策略概率不能全部为 0")
    return strategy


def _clamp_log_limit(raw: str | int | None, default: int = DEFAULT_LOG_LIMIT) -> int:
    try:
        value = int(raw or default)
    except (TypeError, ValueError):
        value = default
    return min(MAX_LOG_LIMIT, max(1, value))


def tail_lines(path: str | os.PathLike[str], limit: int = DEFAULT_LOG_LIMIT) -> list[str]:
    limit = _clamp_log_limit(limit)
    target = Path(path).resolve()
    if not target.is_file():
        return []

    block_size = 8192
    data = b""
    with target.open("rb") as fp:
        fp.seek(0, os.SEEK_END)
        position = fp.tell()
        while position > 0 and data.count(b"\n") <= limit:
            read_size = min(block_size, position)
            position -= read_size
            fp.seek(position)
            data = fp.read(read_size) + data

    return [line.decode("utf-8", "replace") for line in data.splitlines()[-limit:]]


def mask_sensitive(value: Any) -> str:
    text = str(value or "")
    text = _BEARER_PATTERN.sub(r"\1 [MASKED]", text)
    text = _SENSITIVE_ASSIGNMENT_PATTERN.sub(r"\1\2[MASKED]", text)
    return re.sub(r"(?i)(access_token=)[^&\s]+", r"\1[MASKED]", text)


def parse_log_line(raw: str) -> dict[str, Any]:
    masked = mask_sensitive(raw)
    lowered = masked.lower()
    category = "system"
    if "[vocat]" in lowered or "[vocat_expr]" in lowered or "poll deliver" in lowered or "ack command_id" in lowered or "/vocat/webhook" in lowered:
        category = "vocat"
    elif "[vision]" in lowered:
        category = "vision"
    elif "[reaction]" in lowered or "[reaction_follow]" in lowered:
        category = "reaction"
    elif "[ocai]" in lowered or "[kimi]" in lowered or "prompt_tokens" in lowered or "completion_tokens" in lowered:
        category = "llm"
    elif "[webhook] recv private" in lowered or "[private_chat]" in lowered or "[send_private]" in lowered:
        category = "private"
    elif "[webhook] recv group" in lowered or "[group_chat]" in lowered or "[send_group]" in lowered or "[route] 群聊" in masked:
        category = "group"
    elif "[scheduler]" in lowered or "[daily]" in lowered or "[schedule]" in lowered or "reminder" in lowered:
        category = "scheduler"
    elif (
        "[skill]" in lowered
        or "image_understanding" in lowered
        or "file_understanding" in lowered
        or "desktop_agent" in lowered
        or "browser_agent" in lowered
        or "weather" in lowered
        or "overview" in lowered
        or "schedule" in lowered
    ):
        category = "skill"
    elif "napcat 返回" in masked or "retcode" in lowered or "send_group" in lowered or "send_private" in lowered:
        category = "napcat"

    level = "info"
    if re.search(r"(?i)\b(error|exception|traceback|failed|fatal)\b", masked):
        level = "error"
    elif re.search(r"(?i)\b(warning|warn)\b", masked):
        level = "warning"

    fields = {}
    for name, pattern in _FIELD_PATTERNS.items():
        match = pattern.search(masked)
        if match:
            fields[name] = match.group(1)

    return {"category": category, "level": level, "raw": masked, "fields": fields}


def parse_multi_filter_values(raw_values: list[str], allowed_values: set[str]) -> set[str]:
    values: set[str] = set()
    for raw in raw_values:
        for item in str(raw or "").split(","):
            normalized = item.strip().lower()
            if not normalized:
                continue
            if normalized == "all":
                return set()
            if normalized in allowed_values:
                values.add(normalized)
    return values


def _filtered_log_entries() -> list[dict[str, Any]]:
    categories = parse_multi_filter_values(
        request.args.getlist("category") + request.args.getlist("categories"),
        LOG_CATEGORIES - {"all"},
    )
    levels = parse_multi_filter_values(
        request.args.getlist("level") + request.args.getlist("levels"),
        {"info", "warning", "error"},
    )
    keyword = str(request.args.get("keyword") or "").strip().lower()
    group_id = str(request.args.get("group_id") or "").strip()
    user_id = str(request.args.get("user_id") or "").strip()
    limit = _clamp_log_limit(request.args.get("limit"))

    entries = [parse_log_line(line) for line in tail_lines(BRIDGE_LOG_PATH, limit)]
    filtered = []
    for entry in entries:
        fields = entry.get("fields", {})
        raw_lower = entry["raw"].lower()
        if categories and entry["category"] not in categories:
            continue
        if levels and entry["level"] not in levels:
            continue
        if keyword and keyword not in raw_lower:
            continue
        if group_id and fields.get("group_id") != group_id:
            continue
        if user_id and fields.get("user_id") != user_id:
            continue
        filtered.append(entry)
    return filtered


def _probe_napcat_available() -> bool:
    try:
        response = requests.post(
            f"{NAPCAT_HTTP.rstrip('/')}/get_login_info",
            params={"access_token": NAPCAT_TOKEN},
            json={},
            timeout=2,
        )
        if not response.ok:
            return False
        payload = response.json()
        return payload.get("retcode") in {0, "0"} or bool(payload.get("data"))
    except Exception:
        return False


def _masked_id(value: Any) -> str:
    text = str(value or "")
    if not text:
        return ""
    if len(text) <= 4:
        return "*" * len(text)
    return f"{text[:3]}****{text[-3:]}"


def _env_candidates() -> list[dict[str, Any]]:
    paths = (
        ("bridge", QQ_AI_BRIDGE_ROOT / ".env"),
        ("repo", REPO_ROOT / ".env"),
        ("bridge_local", QQ_AI_BRIDGE_ROOT / ".local.env"),
        ("candace_home", Path.home() / ".candace" / "qq-ai-bridge.env"),
    )
    return [{"label": label, "path": str(path), "exists": path.exists()} for label, path in paths]


def _system_config_summary() -> dict[str, Any]:
    return {
        "env_paths": _env_candidates(),
        "bridge_host": os.getenv("BRIDGE_HOST", "0.0.0.0").strip() or "0.0.0.0",
        "bridge_port": os.getenv("BRIDGE_PORT", "5000").strip() or "5000",
        "vocat_webhook_enabled": True,
        "vocat_webhook_token_set": bool(VOCAT_WEBHOOK_TOKEN),
        "vision_api_url_set": bool(os.getenv("VISION_API_URL", "").strip()),
        "vision_api_key_set": bool(os.getenv("VISION_API_KEY", "").strip()),
        "owner_qq": _masked_id(OWNER_QQ),
        "napcat_http_set": bool(NAPCAT_HTTP),
        "napcat_token_set": bool(NAPCAT_TOKEN),
        "kimi_api_key_set": bool(os.getenv("KIMI_API_KEY", "").strip()),
        "openrouter_api_key_set": bool(os.getenv("OPENROUTER_API_KEY", "").strip()),
        "moonshot_api_key_set": bool(os.getenv("MOONSHOT_API_KEY", "").strip()),
        "log_path": str(BRIDGE_LOG_PATH),
    }


def _build_summary() -> dict[str, Any]:
    queue_status = get_vocat_queue_status()
    vocat_status = get_vocat_runtime_status()
    entries = [parse_log_line(line) for line in tail_lines(BRIDGE_LOG_PATH, MAX_LOG_LIMIT)]
    recent_warnings = [entry for entry in entries if entry["level"] in {"warning", "error"}][-10:]
    return {
        "ok": True,
        "bridge_running": True,
        "napcat_available": _probe_napcat_available(),
        "vocat_online": bool(vocat_status.get("device_online")),
        "queue_size": queue_status.get("queue_size", 0),
        "today_group_messages": sum(1 for entry in entries if "[WEBHOOK] recv group" in entry["raw"]),
        "today_private_messages": sum(1 for entry in entries if "[WEBHOOK] recv private" in entry["raw"]),
        "today_vocat_poll": sum(1 for entry in entries if "poll deliver" in entry["raw"]),
        "today_vocat_ack": sum(1 for entry in entries if "ack command_id" in entry["raw"]),
        "recent_warnings": recent_warnings,
        "vocat": vocat_status,
        "config": _system_config_summary(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


@admin_ui_bp.get("/admin")
def admin_console_page():
    return render_template("group_admin.html", initial_section="dashboard")


@admin_ui_bp.get("/admin/groups")
def group_admin_page():
    return render_template("group_admin.html", initial_section="groups")


@admin_ui_bp.get("/admin/logs")
def admin_logs_page():
    return render_template("group_admin.html", initial_section="logs")


@admin_ui_bp.get("/admin/vocat")
def admin_vocat_page():
    return render_template("group_admin.html", initial_section="vocat")


@admin_ui_bp.get("/admin/private")
def admin_private_page():
    return render_template("group_admin.html", initial_section="private")


@admin_ui_bp.get("/admin/system")
def admin_system_page():
    return render_template("group_admin.html", initial_section="system")


@admin_ui_bp.get("/admin/traces")
def admin_traces_page():
    return render_template("group_admin.html", initial_section="traces")


@admin_ui_bp.get("/api/admin/groups")
@admin_ui_bp.get("/admin/api/groups")
def get_group_admin_data():
    return jsonify({"ok": True, **_serialize_group_store()})


@admin_ui_bp.post("/api/admin/groups")
@admin_ui_bp.post("/admin/api/groups")
def save_group_admin_data():
    payload = request.get_json(silent=True) or {}
    groups_payload = payload.get("groups", [])
    if not isinstance(groups_payload, list):
        return jsonify({"ok": False, "error": "groups 必须是数组"}), 400

    current_store = load_group_config_store(GROUP_CONFIG_PATH)
    next_store = {"default": current_store.get("default", {}).copy()}

    for raw in groups_payload:
        if not isinstance(raw, dict):
            continue
        try:
            group_id, merged = _normalize_group_payload(raw, current_store.get(str(raw.get("group_id", "")).strip(), {}))
        except ValueError as exc:
            return jsonify({"ok": False, "error": str(exc)}), 400
        next_store[group_id] = merged

    save_group_config_store(GROUP_CONFIG_PATH, next_store)
    return jsonify({"ok": True, **_serialize_group_store()})


@admin_ui_bp.post("/admin/api/group/update")
def update_group_strategy():
    payload = request.get_json(silent=True) or {}
    group_id = str(payload.get("group_id") or "").strip()
    if not group_id or not group_id.isdigit():
        return jsonify({"ok": False, "error": "group_id 必须是纯数字"}), 400
    if "strategy" not in payload:
        return jsonify({"ok": False, "error": "strategy 必填"}), 400
    try:
        strategy = _normalize_strategy_payload(payload.get("strategy"))
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400

    store = load_group_config_store(GROUP_CONFIG_PATH)
    existing = store.get(group_id)
    if not isinstance(existing, dict):
        return jsonify({"ok": False, "error": "group not found"}), 404
    merged = existing.copy()
    merged["strategy"] = strategy
    merged.pop("strategy_config", None)
    store[group_id] = merged
    save_group_config_store(GROUP_CONFIG_PATH, store)
    return jsonify({"ok": True, "group_id": group_id, "strategy": strategy})


@admin_ui_bp.get("/admin/api/summary")
def get_admin_summary():
    return jsonify(_build_summary())


@admin_ui_bp.get("/admin/api/logs")
def get_admin_logs():
    limit = _clamp_log_limit(request.args.get("limit"))
    return jsonify(
        {
            "ok": True,
            "log_path": str(BRIDGE_LOG_PATH),
            "limit": limit,
            "entries": _filtered_log_entries(),
        }
    )


@admin_ui_bp.get("/admin/api/vocat/status")
def get_admin_vocat_status():
    return jsonify(get_vocat_runtime_status())


@admin_ui_bp.get("/admin/api/traces")
def get_admin_traces():
    return jsonify({"ok": True, "traces": list_traces()})


@admin_ui_bp.get("/admin/api/trace/<trace_id>")
def get_admin_trace(trace_id: str):
    trace = get_trace(trace_id)
    if not trace:
        return jsonify({"ok": False, "error": "trace not found"}), 404
    return jsonify({"ok": True, "trace": trace})


def register_admin_routes(app):
    app.register_blueprint(admin_ui_bp)
