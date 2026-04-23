"""Browser-agent HTTP client, task store, and agent loop."""

from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import requests

from shared.ai.llm_client import call_ai

from apps.qq_ai_bridge.config.settings import (
    AGENT_CANCEL_COMMANDS,
    AGENT_CONTINUE_COMMANDS,
    BROWSER_AGENT_HTTP_TIMEOUT_SECONDS,
    BROWSER_AGENT_LOOP_PROMPT,
    BROWSER_AGENT_MAX_REPEAT_ACTIONS,
    BROWSER_AGENT_MAX_STEPS,
    BROWSER_AGENT_MAX_TASKS,
    BROWSER_AGENT_TASKS_PATH,
    PC_AGENT_URL,
)

_TASK_LOCK = threading.Lock()
_TASKS_CACHE: dict[str, Any] | None = None
_URL_OR_DOMAIN_RE = re.compile(
    r"\b(https?://\S+|[a-z0-9][a-z0-9\-]*\.(?:com|cn|edu|edu\.cn|org|net|io|app|xyz)(?:/\S*)?)\b",
    re.IGNORECASE,
)
_LOGIN_MARKERS = ("sign in", "login", "登录", "统一身份认证", "sso", "verify", "验证码", "人机验证")
_HIGH_RISK_MARKERS = {
    "bilibili": "B站存在风控风险，建议先人工完成登录或验证码，再让我继续。",
    "小红书": "小红书存在风控风险，建议先人工完成登录或验证码，再让我继续。",
    "xiaohongshu": "小红书存在风控风险，建议先人工完成登录或验证码，再让我继续。",
    "rednote": "小红书存在风控风险，建议先人工完成登录或验证码，再让我继续。",
}
_DEADLINE_MARKERS = ("due", "deadline", "ddl", "assignment", "timeline", "作业", "截止")
_ALLOWED_BROWSER_ACTIONS = {"open_url", "click_text", "find_text", "ocr", "extract_deadline", "wait", "scroll"}
_BROWSER_ACTION_ROUTES = {
    "health": ("GET", "/browser/health"),
    "open_url": ("POST", "/browser/open_url"),
    "click_text": ("POST", "/browser/click_text"),
    "find_text": ("POST", "/browser/find_text"),
    "ocr": ("GET", "/browser/ocr"),
    "extract_deadline": ("POST", "/browser/extract_deadline"),
    "screenshot": ("POST", "/browser/screenshot"),
    "wait": ("POST", "/wait"),
    "scroll": ("POST", "/scroll"),
}


def get_browser_agent_endpoint() -> str:
    """Return the local browser-agent endpoint base URL."""
    return os.environ.get("PC_BROWSER_AGENT_URL", PC_AGENT_URL).rstrip("/")


def build_browser_agent_request(action: str, params: dict | None = None) -> dict[str, Any]:
    """Build a normalized browser-agent request payload."""
    return {"action": action, "params": params or {}, "endpoint": get_browser_agent_endpoint()}


def _task_store_path() -> Path:
    return Path(BROWSER_AGENT_TASKS_PATH)


def _ensure_task_store_dir() -> None:
    _task_store_path().parent.mkdir(parents=True, exist_ok=True)


def _load_task_store() -> dict[str, Any]:
    global _TASKS_CACHE
    with _TASK_LOCK:
        if _TASKS_CACHE is not None:
            return _TASKS_CACHE
        path = _task_store_path()
        if not path.exists():
            _TASKS_CACHE = {"tasks": []}
            return _TASKS_CACHE
        try:
            _TASKS_CACHE = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            _TASKS_CACHE = {"tasks": []}
        if not isinstance(_TASKS_CACHE, dict):
            _TASKS_CACHE = {"tasks": []}
        if not isinstance(_TASKS_CACHE.get("tasks"), list):
            _TASKS_CACHE["tasks"] = []
        return _TASKS_CACHE


def _save_task_store(store: dict[str, Any]) -> None:
    global _TASKS_CACHE
    with _TASK_LOCK:
        _TASKS_CACHE = store
        _ensure_task_store_dir()
        _task_store_path().write_text(
            json.dumps(store, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def _upsert_task(task: dict[str, Any]) -> dict[str, Any]:
    store = _load_task_store()
    tasks = [item for item in store.get("tasks", []) if item.get("task_id") != task.get("task_id")]
    tasks.append(task)
    tasks.sort(key=lambda item: int(item.get("updated_at", 0)), reverse=True)
    store["tasks"] = tasks[:BROWSER_AGENT_MAX_TASKS]
    _save_task_store(store)
    return task


def _recent_task_for_user(user_id: int) -> dict[str, Any] | None:
    tasks = _load_task_store().get("tasks", [])
    for task in tasks:
        if int(task.get("user_id", 0)) == int(user_id):
            return task
    return None


def _update_task(task: dict[str, Any], **changes: Any) -> dict[str, Any]:
    task.update(changes)
    task["updated_at"] = int(time.time())
    return _upsert_task(task)


def _new_task(user_id: int, task_text: str, source_skill: str) -> dict[str, Any]:
    now = int(time.time())
    task = {
        "task_id": uuid.uuid4().hex[:12],
        "user_id": user_id,
        "source_skill": source_skill,
        "task": task_text,
        "last_step": "created",
        "last_action": "",
        "last_ocr_text": "",
        "recent_results": [],
        "status": "running",
        "updated_at": now,
        "created_at": now,
    }
    return _upsert_task(task)


def _append_result(task: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
    recent = list(task.get("recent_results", []))
    recent.append(result)
    recent = recent[-8:]
    return _update_task(task, recent_results=recent)


def _extract_json_object(text: str) -> dict[str, Any]:
    raw = (text or "").strip()
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        return {}
    try:
        data = json.loads(match.group(0))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}


def _extract_target_url(text: str) -> str:
    match = _URL_OR_DOMAIN_RE.search(text or "")
    if not match:
        return ""
    value = match.group(1).strip()
    if value.startswith(("http://", "https://")):
        return value
    return f"https://{value}"


def _contains_any(text: str, markers: tuple[str, ...] | list[str]) -> bool:
    low = (text or "").lower()
    return any(marker.lower() in low for marker in markers)


def _high_risk_note(task_text: str) -> str:
    low = (task_text or "").lower()
    for marker, message in _HIGH_RISK_MARKERS.items():
        if marker in low:
            return message
    return ""


def _http_error_payload(action: str, message: str, error_code: str) -> dict[str, Any]:
    return {
        "action": action,
        "status": "error",
        "error_code": error_code,
        "message": message,
        "data": {},
    }


def request_browser_action(
    action: str,
    params: dict[str, Any] | None = None,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Call the local pc-agent browser endpoint and normalize the response."""
    params = params or {}
    if action not in _BROWSER_ACTION_ROUTES:
        return _http_error_payload(action, f"Unsupported browser action: {action}", "unsupported_action")

    method, route = _BROWSER_ACTION_ROUTES[action]
    url = f"{get_browser_agent_endpoint()}{route}"
    request_payload = build_browser_agent_request(action, params)
    request_payload["task_id"] = task_id

    try:
        if method == "GET":
            response = requests.get(url, params=params, timeout=BROWSER_AGENT_HTTP_TIMEOUT_SECONDS)
        else:
            response = requests.post(url, json=params, timeout=BROWSER_AGENT_HTTP_TIMEOUT_SECONDS)
    except requests.Timeout:
        return _http_error_payload(action, "Browser action timed out.", "timeout")
    except requests.ConnectionError:
        return _http_error_payload(action, "pc-agent is unreachable.", "agent_unreachable")
    except requests.RequestException as exc:
        return _http_error_payload(action, f"Browser request failed: {exc}", "request_failed")

    try:
        payload = response.json()
    except ValueError:
        payload = {"status": "error", "message": response.text}

    status = str(payload.get("status", "error"))
    error_code = str(payload.get("error_code", "")).strip()
    message = str(payload.get("message") or payload.get("error") or "").strip()
    if status == "not_found" and not error_code:
        error_code = "text_not_found"
    if status == "error" and not error_code:
        error_code = "browser_error"

    return {
        "action": action,
        "params": params,
        "task_id": task_id,
        "status": status,
        "error_code": error_code,
        "message": message,
        "data": payload,
        "endpoint": request_payload["endpoint"],
        "http_status": response.status_code,
    }


def _browser_observation(task: dict[str, Any]) -> dict[str, Any]:
    health = request_browser_action("health", task_id=task["task_id"])
    ocr = request_browser_action("ocr", task_id=task["task_id"])
    return {
        "health": health,
        "ocr": ocr,
        "page_text": str((ocr.get("data") or {}).get("text", "") or ""),
        "active_url": str((health.get("data") or {}).get("active_tab_url", "") or ""),
        "page_title": str((health.get("data") or {}).get("page_title", "") or ""),
    }


def _manual_takeover_reason(page_text: str, active_url: str, task_text: str) -> str:
    combined = "\n".join(filter(None, [page_text, active_url, task_text]))
    if not _contains_any(combined, _LOGIN_MARKERS):
        return ""
    if "验证码" in combined or "verify" in combined.lower() or "captcha" in combined.lower():
        return "检测到验证码或验证页，请先在本机浏览器完成人工验证，然后回复“继续任务”。"
    return "检测到登录或 SSO 页面，请先在本机浏览器完成登录，然后回复“继续任务”。"


def _summarize_deadlines(items: list[dict[str, Any]]) -> str:
    if not items:
        return "暂时还没找到明确的 DDL。"
    preview = "；".join(item.get("text", "") for item in items[:3] if item.get("text"))
    return f"已找到 {len(items)} 条 DDL：{preview}" if preview else f"已找到 {len(items)} 条 DDL。"


def _action_signature(action: dict[str, Any]) -> str:
    return json.dumps(
        {"action": action.get("action"), "params": action.get("params", {})},
        ensure_ascii=False,
        sort_keys=True,
    )


def _build_loop_prompt(task: dict[str, Any], observation: dict[str, Any]) -> str:
    payload = {
        "task": task.get("task", ""),
        "task_id": task.get("task_id", ""),
        "last_step": task.get("last_step", ""),
        "last_action": task.get("last_action", ""),
        "last_ocr_text": str(task.get("last_ocr_text", ""))[:2000],
        "recent_results": task.get("recent_results", [])[-4:],
        "observation": {
            "active_url": observation.get("active_url", ""),
            "page_text": observation.get("page_text", "")[:2500],
        },
    }
    return f"{BROWSER_AGENT_LOOP_PROMPT}\n\n当前上下文：\n{json.dumps(payload, ensure_ascii=False, indent=2)}"


def _plan_next_actions(task: dict[str, Any], observation: dict[str, Any]) -> dict[str, Any]:
    task_text = str(task.get("task", "") or "")
    active_url = observation.get("active_url", "")
    page_text = observation.get("page_text", "")

    if not active_url:
        target_url = _extract_target_url(task_text)
        if target_url:
            return {
                "reply": f"我先打开 {target_url}。",
                "done": False,
                "actions": [{"action": "open_url", "params": {"url": target_url}}],
            }

    if _contains_any(page_text, _DEADLINE_MARKERS):
        return {
            "reply": "我已经看到疑似 DDL 线索，先提取结果。",
            "done": False,
            "actions": [{"action": "extract_deadline", "params": {}}],
        }

    prompt = _build_loop_prompt(task, observation)
    response_text = call_ai(prompt)
    parsed = _extract_json_object(response_text)
    actions = parsed.get("actions", [])
    if not isinstance(actions, list):
        actions = []
    sanitized_actions = []
    for action in actions[:2]:
        if not isinstance(action, dict):
            continue
        action_name = str(action.get("action", "")).strip()
        if action_name not in _ALLOWED_BROWSER_ACTIONS:
            continue
        params = action.get("params", {})
        if not isinstance(params, dict):
            params = {}
        sanitized_actions.append({"action": action_name, "params": params})

    return {
        "reply": str(parsed.get("reply", "") or "我继续观察并尝试下一步。").strip(),
        "done": bool(parsed.get("done", False)),
        "actions": sanitized_actions,
    }


def _finalize_task(task: dict[str, Any], status: str, last_step: str, reply: str) -> dict[str, Any]:
    task = _update_task(task, status=status, last_step=last_step)
    return {"status": status, "task": task, "reply": reply}


def _result_summary(result: dict[str, Any]) -> str:
    action = result.get("action", "")
    status = result.get("status", "")
    data = result.get("data", {}) or {}
    if action == "extract_deadline" and status == "ok":
        return _summarize_deadlines(data.get("items", []))
    if status == "ok":
        return f"{action} 已执行。"
    if status == "not_found":
        return f"{action} 未找到目标。"
    message = result.get("message") or result.get("error_code") or "动作失败"
    return f"{action} 失败：{message}"


def _run_agent_loop(task: dict[str, Any]) -> dict[str, Any]:
    seen_signatures: dict[str, int] = {}
    last_observation = ""
    unchanged_observation_count = 0

    for step in range(1, BROWSER_AGENT_MAX_STEPS + 1):
        observation = _browser_observation(task)
        page_text = observation.get("page_text", "")
        active_url = observation.get("active_url", "")
        task = _update_task(task, last_step=f"observe_{step}", last_ocr_text=page_text[:1200])

        manual_reason = _manual_takeover_reason(page_text, active_url, task.get("task", ""))
        if manual_reason:
            return _finalize_task(task, "manual_attention", f"manual_attention_{step}", manual_reason)

        observation_fingerprint = f"{active_url}\n{page_text[:800]}"
        if observation_fingerprint == last_observation:
            unchanged_observation_count += 1
        else:
            unchanged_observation_count = 0
            last_observation = observation_fingerprint
        if unchanged_observation_count >= 2:
            reply = "页面连续两轮几乎没变化，我先停在当前步骤，建议你人工接管后再回复“继续任务”。"
            return _finalize_task(task, "stalled", f"stalled_{step}", reply)

        deadline_result = request_browser_action("extract_deadline", {}, task_id=task["task_id"])
        task = _append_result(task, deadline_result)
        if deadline_result.get("status") == "ok" and (deadline_result.get("data", {}) or {}).get("count", 0) > 0:
            summary = _summarize_deadlines((deadline_result.get("data") or {}).get("items", []))
            return _finalize_task(task, "completed", f"deadline_found_{step}", summary)

        plan = _plan_next_actions(task, observation)
        actions = plan.get("actions", []) if not plan.get("done") else []
        if plan.get("done") and not actions:
            reply = str(plan.get("reply", "") or "任务已结束。")
            return _finalize_task(task, "completed", f"planner_done_{step}", reply)
        if not actions:
            reply = "我暂时想不到安全的下一步，建议你人工接管后再继续。"
            return _finalize_task(task, "stalled", f"no_actions_{step}", reply)

        for action in actions:
            signature = _action_signature(action)
            seen_signatures[signature] = seen_signatures.get(signature, 0) + 1
            if seen_signatures[signature] > BROWSER_AGENT_MAX_REPEAT_ACTIONS:
                reply = f"动作 {action['action']} 已重复过多次，我先停下，建议人工接管。"
                return _finalize_task(task, "stalled", f"repeat_{step}", reply)

            result = request_browser_action(action["action"], action.get("params", {}), task_id=task["task_id"])
            task = _update_task(task, last_action=action["action"], last_step=f"{action['action']}_{step}")
            task = _append_result(task, result)

            if result.get("status") == "error":
                message = result.get("message") or result.get("error_code") or "未知错误"
                if result.get("error_code") in {"timeout", "agent_unreachable"}:
                    return _finalize_task(task, "failed", f"{action['action']}_{step}", message)
                if result.get("error_code") == "text_not_found":
                    continue
                return _finalize_task(task, "failed", f"{action['action']}_{step}", _result_summary(result))

            if result.get("status") == "ok" and action["action"] == "extract_deadline":
                data = result.get("data", {}) or {}
                if data.get("count", 0) > 0:
                    return _finalize_task(
                        task,
                        "completed",
                        f"extract_deadline_{step}",
                        _summarize_deadlines(data.get("items", [])),
                    )

    reply = "已达到最大尝试步数，当前还没稳定拿到结果。建议你人工接管后再回复“继续任务”。"
    return _finalize_task(task, "stalled", "max_steps", reply)


def _cancel_task(user_id: int) -> dict[str, Any]:
    task = _recent_task_for_user(user_id)
    if task is None:
        return {"status": "noop", "reply": "目前没有可取消的浏览器任务。"}
    _update_task(task, status="cancelled", last_step="cancelled")
    return {"status": "cancelled", "reply": "已取消最近的浏览器任务。"}


def _continue_task(user_id: int, source_skill: str) -> dict[str, Any]:
    task = _recent_task_for_user(user_id)
    if task is None:
        return {"status": "noop", "reply": "目前没有可继续的浏览器任务。"}
    task = _update_task(task, status="running", source_skill=source_skill)
    result = _run_agent_loop(task)
    risk_note = _high_risk_note(task.get("task", ""))
    if risk_note and risk_note not in result["reply"]:
        result["reply"] = f"{result['reply']} {risk_note}".strip()
    return result


def run_browser_agent_task(user_id: int, command: str, source_skill: str = "browser_agent") -> dict[str, Any]:
    """Run or continue a browser-agent task for one user."""
    normalized = (command or "").strip()
    if normalized in AGENT_CANCEL_COMMANDS:
        return _cancel_task(user_id)
    if normalized in AGENT_CONTINUE_COMMANDS:
        return _continue_task(user_id, source_skill)

    task = _new_task(user_id, normalized, source_skill)
    target_url = _extract_target_url(normalized)
    if target_url:
        open_result = request_browser_action("open_url", {"url": target_url}, task_id=task["task_id"])
        task = _update_task(task, last_step="open_url", last_action="open_url")
        task = _append_result(task, open_result)
        if open_result.get("status") == "error":
            reply = open_result.get("message") or "打开页面失败。"
            return _finalize_task(task, "failed", "open_url", reply)

    result = _run_agent_loop(task)
    risk_note = _high_risk_note(normalized)
    if risk_note and risk_note not in result["reply"]:
        result["reply"] = f"{result['reply']} {risk_note}".strip()
    return result


__all__ = [
    "build_browser_agent_request",
    "get_browser_agent_endpoint",
    "request_browser_action",
    "run_browser_agent_task",
]
