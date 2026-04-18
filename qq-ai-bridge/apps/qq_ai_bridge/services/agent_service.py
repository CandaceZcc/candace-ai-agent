import json
import logging
from typing import Any, Dict

import requests

from shared.ai.llm_client import call_ai
from apps.qq_ai_bridge.config.settings import (
    AGENT_SYSTEM_PROMPT,
    ALLOWED_ACTIONS,
    PC_AGENT_URL,
)


logger = logging.getLogger(__name__)


def call_pc_agent_api(endpoint: str, data: Dict[str, Any], timeout: int = 10) -> Dict[str, Any]:
    """Call an endpoint on the PC Agent service."""
    url = f"{PC_AGENT_URL.rstrip('/')}/{endpoint.lstrip('/')}"
    try:
        response = requests.post(url, json=data, timeout=timeout)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        logger.error("PC Agent communication failed: %s", e)
        return {"status": "error", "message": f"Agent communication failed: {e}"}


def execute_agent_plan(user_id: int, plan: Dict[str, Any]) -> Dict[str, Any]:
    """Execute a parsed JSON plan from the LLM."""
    actions = plan.get("actions", [])
    results = []

    for action in actions:
        action_name = action.get("action")
        if action_name not in ALLOWED_ACTIONS:
            results.append({
                "status": "error",
                "message": f"Action '{action_name}' is not allowed."
            })
            continue

        params = action.get("params", {})
        try:
            res = call_pc_agent_api(f"execute/{action_name}", data=params)
            results.append(res)
        except requests.RequestException as e:
            results.append({"status": "error", "message": str(e)})

    return {"status": "completed", "results": results}


def get_agent_session(user_id: int) -> Dict[str, Any]:
    """Retrieve the current session state for an agent user."""
    try:
        res = call_pc_agent_api("session/get", data={"user_id": user_id})
        return res if res.get("status") == "ok" else {}
    except requests.RequestException as e:
        logger.error("Failed to retrieve agent session key: %s", e)
        return {}


def reset_agent_session(user_id: int) -> Dict[str, Any]:
    """Reset the agent session."""
    return call_pc_agent_api("session/reset", data={"user_id": user_id})


def observe_screen_text(user_id: int) -> Dict[str, Any]:
    """Observe text currently visible on the screen."""
    return call_pc_agent_api("observe", data={"user_id": user_id})


def summarize_agent_issue(user_id: int, history: list) -> str:
    """Summarize an issue encountered by the agent."""
    if not history:
        return "No history available to summarize."

    history_json = json.dumps(history, indent=2, ensure_ascii=False)
    summary_prompt = f"Summarize the following agent issues:\n{history_json}"
    return call_agent_llm(summary_prompt, system_prompt="You are a helpful error summarizer.")


def call_agent_llm(prompt: str, system_prompt: str | None = None) -> str:
    """Call the LLM with a specific prompt, typically for agent reasoning."""
    system_prompt = system_prompt or AGENT_SYSTEM_PROMPT
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt}
    ]
    try:
        return call_ai(messages)
    except Exception as e:
        logger.error("LLM call failed: %s", e)
        return json.dumps({"status": "error", "message": "Failed to call LLM"})


def agent_llm_plan(user_id: int, task: str) -> Dict[str, Any]:
    """Ask the LLM to generate a plan for a given task."""
    session = get_agent_session(user_id)
    session_json = json.dumps(session, indent=2, ensure_ascii=False)
    prompt = f"Task: {task}\nCurrent session state:\n{session_json}"

    try:
        response_text = call_agent_llm(prompt)
        plan = json.loads(response_text)
        return plan
    except json.JSONDecodeError as e:
        logger.error("Failed to parse LLM plan: %s", e)
        return {"status": "error", "message": "Failed to parse JSON plan"}


def execute_agent_workflow(user_id: int, task: str) -> Dict[str, Any]:
    """High-level workflow: generate plan and execute it."""
    plan = agent_llm_plan(user_id, task)
    if plan.get("status") == "error":
        return plan

    return execute_agent_plan(user_id, plan)


def handle_pc_agent_command(user_id: int, command: str) -> Dict[str, Any]:
    """Parse and handle a raw command text from the user."""
    if command.strip().lower() == "reset":
        return reset_agent_session(user_id)
    elif command.strip().lower() == "observe":
        return observe_screen_text(user_id)
    else:
        return execute_agent_workflow(user_id, command)
