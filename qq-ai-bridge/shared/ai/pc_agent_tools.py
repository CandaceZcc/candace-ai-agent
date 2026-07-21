"""Agents SDK function-tool wrappers for the existing local PC Agent."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any
from urllib.parse import urlparse

from agents import function_tool
from apps.qq_ai_bridge.services.browser_agent_service import request_browser_action

_HIGH_IMPACT_TOKENS = (
    "submit",
    "send",
    "pay",
    "purchase",
    "buy",
    "delete",
    "upload",
    "download",
    "sign in",
    "log in",
    "login",
    "security warning",
    "ignore warning",
    "bypass",
    "付款",
    "支付",
    "提交",
    "发送",
    "删除",
    "上传",
    "下载",
    "登录",
    "登入",
    "登陆",
    "安全警告",
    "继续访问",
)


@dataclass(frozen=True)
class PcActionResult:
    ok: bool
    action: str
    message: str
    needs_approval: bool = False
    approval_reason: str | None = None
    data: dict[str, Any] = field(default_factory=dict, repr=False)


async def pc_agent_status() -> PcActionResult:
    """Return local PC Agent browser health."""
    payload = request_browser_action("health", {})
    return _result_from_payload("pc_agent_status", payload, success_message="pc-agent ok")


async def pc_open_http_url(url: str) -> PcActionResult:
    """Open an HTTP(S) URL in the local browser runtime."""
    cleaned = str(url or "").strip()
    parsed = urlparse(cleaned)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return PcActionResult(False, "pc_open_http_url", "Only http and https URLs are allowed.")
    payload = request_browser_action("open_url", {"url": cleaned})
    return _result_from_payload("pc_open_http_url", payload, success_message="URL opened")


async def pc_capture_screen() -> PcActionResult:
    """Capture the current browser screen without exposing local file paths."""
    payload = request_browser_action("screenshot", {})
    result = _result_from_payload("pc_capture_screen", payload, success_message="screen captured")
    if result.ok:
        return PcActionResult(True, result.action, "screen captured", data={})
    return result


async def pc_browser_inspect() -> PcActionResult:
    """Read visible browser text from the local browser runtime."""
    payload = request_browser_action("ocr", {})
    data = payload.get("data") or {}
    if payload.get("status") == "ok":
        text = str(data.get("text") or "")[:1200]
        message = text or "No visible browser text was returned."
        return PcActionResult(True, "pc_browser_inspect", message, data={"text": text})
    return _result_from_payload("pc_browser_inspect", payload)


async def pc_browser_click_text(text: str) -> PcActionResult:
    """Click visible browser text when the action is low-impact."""
    target = str(text or "").strip()
    if _requires_approval(target):
        return PcActionResult(
            False,
            "pc_browser_click_text",
            "Approval required before this computer action.",
            needs_approval=True,
            approval_reason="approval required for high-impact browser action",
        )
    payload = request_browser_action("click_text", {"text": target})
    return _result_from_payload("pc_browser_click_text", payload, success_message="text clicked")


def get_pc_agent_tool(name: str):
    """Return an SDK function tool for an allowlisted local PC Agent operation."""
    mapping = {
        "pc_agent_status": _pc_agent_status_tool,
        "pc_open_http_url": _pc_open_http_url_tool,
        "pc_capture_screen": _pc_capture_screen_tool,
        "pc_browser_inspect": _pc_browser_inspect_tool,
        "pc_browser_click_text": _pc_browser_click_text_tool,
    }
    try:
        return mapping[name]
    except KeyError as exc:
        raise ValueError(f"unsupported pc agent tool: {name}") from exc


@function_tool(name_override="pc_agent_status")
async def _pc_agent_status_tool() -> dict[str, Any]:
    """Check whether the local PC Agent browser runtime is reachable."""
    return asdict(await pc_agent_status())


@function_tool(name_override="pc_open_http_url")
async def _pc_open_http_url_tool(url: str) -> dict[str, Any]:
    """Open an HTTP or HTTPS URL in the local browser runtime."""
    return asdict(await pc_open_http_url(url))


@function_tool(name_override="pc_capture_screen")
async def _pc_capture_screen_tool() -> dict[str, Any]:
    """Capture the browser screen and return a redacted result."""
    return asdict(await pc_capture_screen())


@function_tool(name_override="pc_browser_inspect")
async def _pc_browser_inspect_tool() -> dict[str, Any]:
    """Read visible text from the local browser runtime."""
    return asdict(await pc_browser_inspect())


@function_tool(name_override="pc_browser_click_text")
async def _pc_browser_click_text_tool(text: str) -> dict[str, Any]:
    """Click low-impact visible text in the local browser runtime."""
    return asdict(await pc_browser_click_text(text))


def _result_from_payload(
    action: str,
    payload: dict[str, Any],
    *,
    success_message: str | None = None,
) -> PcActionResult:
    status = str(payload.get("status") or "").lower()
    error_code = str(payload.get("error_code") or "").strip()
    if status == "ok":
        return PcActionResult(True, action, success_message or "ok", data=_safe_data(payload))
    if error_code == "timeout":
        return PcActionResult(False, action, "PC Agent action timed out.")
    if error_code == "agent_unreachable":
        return PcActionResult(False, action, "PC Agent is unreachable.")
    message = str(payload.get("message") or error_code or "PC Agent action failed.").strip()
    return PcActionResult(False, action, message)


def _safe_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data") or {}
    if not isinstance(data, dict):
        return {}
    safe = dict(data)
    safe.pop("path", None)
    safe.pop("screenshot_path", None)
    return safe


def _requires_approval(text: str) -> bool:
    lowered = str(text or "").lower()
    return any(token in lowered or token in text for token in _HIGH_IMPACT_TOKENS)


__all__ = [
    "PcActionResult",
    "get_pc_agent_tool",
    "pc_agent_status",
    "pc_browser_click_text",
    "pc_browser_inspect",
    "pc_capture_screen",
    "pc_open_http_url",
]
