"""Admin UI routes for managing group whitelist and reply policy."""

from __future__ import annotations

from flask import Blueprint, jsonify, render_template, request

from storage_utils import load_group_config_store, save_group_config_store

from apps.qq_ai_bridge.config.settings import GROUP_CONFIG_PATH

admin_ui_bp = Blueprint("admin_ui", __name__)

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

    for field in _EDITABLE_GROUP_FIELDS:
        if field in raw and field != "reply_all_messages":
            merged[field] = bool(raw.get(field))

    return group_id, merged


@admin_ui_bp.get("/admin/groups")
def group_admin_page():
    return render_template("group_admin.html")


@admin_ui_bp.get("/api/admin/groups")
def get_group_admin_data():
    return jsonify({"ok": True, **_serialize_group_store()})


@admin_ui_bp.post("/api/admin/groups")
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


def register_admin_routes(app):
    app.register_blueprint(admin_ui_bp)
