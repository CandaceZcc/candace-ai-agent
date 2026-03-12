"""Desktop-agent planning and execution services."""

import json

import requests

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text
from apps.qq_ai_bridge.config.settings import (
    AGENT_CANCEL_COMMANDS,
    AGENT_CONTINUE_COMMANDS,
    AGENT_MAX_HISTORY,
    AGENT_MAX_ITERATIONS,
    AGENT_MAX_OCR_CHARS,
    AGENT_MAX_REPEAT_WORKFLOW,
    AGENT_SESSION_MEMORY,
    AGENT_SYSTEM_PROMPT,
    ALLOWED_ACTIONS,
    PC_AGENT_URL,
)
from apps.qq_ai_bridge.services.prompt_service import build_vision_user_text
from shared.ai.llm_client import call_ai


def call_pc_agent_api(action, params=None, timeout=15):
    """Call the pc-agent HTTP API."""
    try:
        if params:
            resp = requests.post(f"{PC_AGENT_URL}/{action}", json=params, timeout=timeout)
        else:
            resp = requests.get(f"{PC_AGENT_URL}/{action}", timeout=timeout)

        text = resp.text
        try:
            payload = resp.json()
        except Exception:
            payload = None
        return text, payload
    except Exception as e:
        return f"pc-agent error: {e}", None


def get_agent_session(user_id) -> dict:
    """Return in-memory session state for a user."""
    key = str(user_id)
    session = AGENT_SESSION_MEMORY.get(key)
    if session is None:
        session = {
            "task": "",
            "last_user_command": "",
            "last_ocr_text": "",
            "recent_results": [],
        }
        AGENT_SESSION_MEMORY[key] = session
    return session


def reset_agent_session(user_id):
    """Reset in-memory agent session state."""
    AGENT_SESSION_MEMORY.pop(str(user_id), None)


def observe_screen_text():
    """Capture OCR text from pc-agent for agent replanning."""
    raw_text, payload = call_pc_agent_api("ocr", timeout=20)
    if isinstance(payload, dict):
        text = normalize_query_text(payload.get("text", ""))
        return {"raw": raw_text, "text": text[:AGENT_MAX_OCR_CHARS]}
    return {"raw": raw_text, "text": ""}


def call_agent_llm(prompt: str, user_text: str) -> str:
    """Call the LLM for agent planning."""
    llm_input = f"{prompt.strip()}\n\n用户指令：{user_text.strip()}"
    return call_ai(llm_input)


def agent_llm_plan(user_text: str, session=None) -> dict:
    """Create the next agent plan from task/session context."""
    context = {
        "task": (session or {}).get("task", ""),
        "latest_user_command": user_text.strip(),
        "last_ocr_text": (session or {}).get("last_ocr_text", ""),
        "recent_results": (session or {}).get("recent_results", [])[-AGENT_MAX_HISTORY:],
    }
    content = call_agent_llm(AGENT_SYSTEM_PROMPT, json.dumps(context, ensure_ascii=False))
    print(f"[AGENT] LLM raw output: {content!r}")

    try:
        obj = json.loads(content)
        if not isinstance(obj, dict):
            raise ValueError("top-level JSON is not an object")
        return obj
    except Exception as e:
        return {"reply": f"LLM返回不是合法JSON: {e}", "done": True, "actions": []}


def execute_agent_plan(plan: dict) -> str:
    """Execute a single pc-agent action."""
    action = plan.get("action")
    params = plan.get("params", {}) or {}

    if action == "reject":
        return f"拒绝执行：{params.get('reason', '未知原因')}"

    if action not in ALLOWED_ACTIONS:
        return f"非法 action: {action}"

    if action == "launch_and_open":
        url = str(params.get("url", "")).strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            return f"拒绝执行：非法 URL {url!r}"

    text, _ = call_pc_agent_api(
        action,
        params=None if action in {"screenshot", "position", "screen_size", "ocr"} else params,
        timeout=15,
    )
    return text


def summarize_agent_issue(step: dict, result: str) -> str:
    """Turn pc-agent raw errors into user-friendly status text."""
    action = str(step.get("action", ""))
    params = step.get("params", {}) or {}
    result = (result or "").strip()

    if not result:
        return ""

    lowered = result.lower()
    if "pc-agent error" in lowered:
        return f"执行 {action} 时出错。"
    if "非法 action" in result or "拒绝执行" in result:
        return result
    if '"status":"not_found"' in result or '"status": "not_found"' in result:
        if action == "click_text":
            target = params.get("text", "")
            return f"屏幕上没找到“{target}”。"
        if action == "find_text":
            target = params.get("text", "")
            return f"屏幕上没找到“{target}”相关文字。"
        return f"{action} 没有找到目标。"
    return ""


def execute_agent_workflow(plan: dict, session: dict) -> str:
    """Execute multi-step agent workflows with OCR feedback loop."""
    last_reply = ""
    issues = []
    last_signature = None
    repeated_signature_count = 0
    current_plan = plan

    for _ in range(AGENT_MAX_ITERATIONS):
        reply = str(current_plan.get("reply", "")).strip()
        if reply:
            last_reply = reply

        done = bool(current_plan.get("done", False))
        actions = current_plan.get("actions")

        if actions is None:
            single_result = execute_agent_plan(current_plan)
            issue = summarize_agent_issue(current_plan, single_result)
            if issue:
                issues.append(issue)
            break

        if not isinstance(actions, list):
            issues.append("拒绝执行：actions 必须是数组")
            break

        if not actions:
            if not done and not reply:
                issues.append("没有可执行动作。")
            break

        signature = json.dumps(actions, ensure_ascii=False, sort_keys=True)
        if signature == last_signature:
            repeated_signature_count += 1
        else:
            last_signature = signature
            repeated_signature_count = 0

        if repeated_signature_count > AGENT_MAX_REPEAT_WORKFLOW:
            issues.append("停止执行：检测到重复 workflow。")
            break

        iteration_results = []
        iteration_issues = []
        for step in actions:
            if not isinstance(step, dict):
                msg = "拒绝执行：actions 内存在非对象步骤"
                iteration_results.append(msg)
                iteration_issues.append(msg)
                continue
            step_result = execute_agent_plan(step)
            iteration_results.append(step_result)
            issue = summarize_agent_issue(step, step_result)
            if issue:
                iteration_issues.append(issue)

        session["recent_results"] = (session.get("recent_results", []) + iteration_results)[-AGENT_MAX_HISTORY:]
        if iteration_issues:
            issues.extend(iteration_issues)

        if done:
            break

        observation = observe_screen_text()
        session["last_ocr_text"] = observation["text"]
        current_plan = agent_llm_plan(session.get("task", ""), session=session)
        print("[AGENT] Next LLM plan =", current_plan)

        if bool(current_plan.get("done", False)) and not current_plan.get("actions"):
            final_reply = str(current_plan.get("reply", "")).strip()
            if final_reply:
                last_reply = final_reply
            break

    final_parts = []
    if last_reply:
        final_parts.append(last_reply)
    if issues:
        final_parts.append("\n".join(issues))
    final_message = "\n\n".join(part for part in final_parts if part).strip()
    return final_message or "没有可执行动作。"


def handle_pc_agent_command(text: str, user_id):
    """Handle private-chat `agent ...` commands."""
    text = (text or "").strip()
    if not text.startswith("agent "):
        return None

    cmd = text[6:].strip()
    if not cmd:
        return "未知 agent 指令"

    session = get_agent_session(user_id)

    if cmd in AGENT_CANCEL_COMMANDS:
        reset_agent_session(user_id)
        return "已清除当前 agent 任务记忆。"

    if cmd in AGENT_CONTINUE_COMMANDS:
        if not session.get("task"):
            return "当前没有可继续的任务。"
        planning_input = f"继续执行任务：{session['task']}"
    else:
        session["task"] = build_vision_user_text(cmd)
        session["last_ocr_text"] = ""
        session["recent_results"] = []
        planning_input = cmd

    session["last_user_command"] = cmd
    plan = agent_llm_plan(planning_input, session=session)
    print("[AGENT] LLM plan =", plan)
    return execute_agent_workflow(plan, session=session)
