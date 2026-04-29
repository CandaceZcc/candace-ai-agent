"""VoCat webhook orchestration and background skill execution."""

from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg_async
from apps.qq_ai_bridge.adapters.vocat_controller import (
    VocatControllerError,
    send_expression,
    send_tts_vocal,
)
from apps.qq_ai_bridge.config.settings import (
    OWNER_QQ,
    SCHEDULE_PATH,
    VOCAT_MD_ROOT,
    VOCAT_QQ_KEYWORDS,
    VOCAT_QQ_FORWARD_USER_ID,
    VOCAT_REMOTE_CONTROL_USERS,
    VOCAT_VOICE_REPLY_TO_QQ,
)
from apps.qq_ai_bridge.services.agent_service import handle_pc_agent_command
from apps.qq_ai_bridge.services.schedule_service import (
    detect_schedule_intent,
    format_today_schedule_reply,
    format_tomorrow_schedule_reply,
    query_today_schedule,
    query_tomorrow_schedule,
)
from apps.qq_ai_bridge.services.weather_service import handle_weather_query
from apps.qq_ai_bridge.services.vocat_command_queue import normalize_vocat_expression, select_vocat_expression
from shared.ai.llm_client import call_kimi_text_async

_VOCAT_EXECUTOR = ThreadPoolExecutor(max_workers=4, thread_name_prefix="vocat")

_QQ_FORWARD_PATTERNS = (
    re.compile(r"^(?:发|转发|告诉)\s*qq", re.IGNORECASE),
    re.compile(r"qq\s*(?:说|发送|转发)", re.IGNORECASE),
)
_MD_READ_PATTERNS = (
    re.compile(r"(?P<path>[\w./\\-]+\.md)\b", re.IGNORECASE),
    re.compile(r"(?:读取|查看|打开|总结)\s+(?P<path>[\w./\\-]+\.md)\b", re.IGNORECASE),
)
_VOICE_REPLY_SOURCES = {
    "vocat_function_call",
    "vocat_voice",
    "vocat_device",
}

_EXPRESSION_KEYWORDS = (
    ("angry", ("angry", "生气", "愤怒", "气死", "怒")),
    ("sleep", ("sleep", "睡觉", "睡眠", "困", "晚安")),
    ("dizzy", ("dizzy", "thinking", "思考", "晕", "想一想")),
    ("blink", ("blink", "眨眼", "眨一下", "待机", "idle")),
    ("happy", ("happy", "开心", "高兴", "微笑", "正常")),
)
_EXPRESSION_COMMAND_WORDS = ("切换", "切到", "显示", "设置", "换", "调", "变成", "改成")


# _extract_query：提取相关逻辑
def _extract_query(data: dict[str, Any]) -> str:
    for key in ("query", "text", "asr_text", "message", "content"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


# _is_qq_forward_query：判断转发查询
def _is_qq_forward_query(query: str) -> bool:
    if any(keyword and keyword in query for keyword in VOCAT_QQ_KEYWORDS):
        return True
    return any(pattern.search(query) for pattern in _QQ_FORWARD_PATTERNS)


# _extract_md_path：提取Markdown路径
def _extract_md_path(query: str) -> Path | None:
    for pattern in _MD_READ_PATTERNS:
        match = pattern.search(query)
        if not match:
            continue
        raw_path = (match.groupdict().get("path") or "").strip()
        if not raw_path:
            continue
        candidate = Path(raw_path).expanduser()
        if not candidate.is_absolute():
            candidate = (VOCAT_MD_ROOT / candidate).resolve()
        else:
            candidate = candidate.resolve()
        try:
            candidate.relative_to(VOCAT_MD_ROOT.resolve())
        except ValueError:
            return None
        return candidate
    return None


# _read_markdown_file：读取Markdown文件
def _read_markdown_file(path: Path) -> str:
    if not path.exists():
        return f"我没有找到这个 Markdown 文件：{path.name}"
    if not path.is_file():
        return f"{path.name} 不是一个可读取的文件。"
    text = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not text:
        return f"{path.name} 是空文件。"
    preview = text[:1200].strip()
    if len(text) > 1200:
        preview += "\n\n[内容已截断]"
    return f"{path.name} 的内容如下：\n{preview}"


def _preview(text: str, limit: int = 80) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    return compact[:limit] + ("..." if len(compact) > limit else "")


def _detect_expression_query(query: str) -> dict[str, Any] | None:
    normalized = str(query or "").strip()
    lowered = normalized.lower()
    mentions_expression = any(token in lowered for token in ("expression", "emotion", "face")) or any(
        token in normalized for token in ("表情", "脸", "眼睛")
    )
    has_expression_command = any(token in normalized for token in _EXPRESSION_COMMAND_WORDS)
    has_expression_value = any(
        keyword in lowered or keyword in normalized
        for _, keywords in _EXPRESSION_KEYWORDS
        for keyword in keywords
    )
    if not mentions_expression and not (has_expression_command and has_expression_value):
        return None

    if normalized.startswith("测试") and "表情" in normalized and len(normalized) <= 12:
        return {
            "handled": True,
            "source": "local_expression_test",
            "reply": "已切换到 happy 表情。",
            "expression": "happy",
        }

    for expression, keywords in _EXPRESSION_KEYWORDS:
        if any(keyword in lowered or keyword in normalized for keyword in keywords):
            return {
                "handled": True,
                "source": "local_expression",
                "reply": f"已切换到 {expression} 表情。",
                "expression": expression,
            }

    if any(token in normalized for token in ("怎么", "如何", "没法", "无法", "不能")) or (
        mentions_expression and any(token in normalized for token in _EXPRESSION_COMMAND_WORDS)
    ):
        return {
            "handled": True,
            "source": "local_expression_help",
            "reply": "可以说：切换开心表情、切换眨眼表情、切换思考表情、切换睡觉表情，或者用 QQ 私聊发送 #表情 happy。",
            "expression": "blink" if not any(token in normalized for token in ("没法", "无法", "不能")) else "dizzy",
        }
    return None


def _payload_bool(data: dict[str, Any], key: str, default: bool) -> bool:
    value = data.get(key)
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return str(value).strip().lower() in {"1", "true", "yes", "on", "y"}


def _should_forward_reply_to_qq(data: dict[str, Any]) -> bool:
    default = VOCAT_VOICE_REPLY_TO_QQ and str(data.get("source", "")).strip() in _VOICE_REPLY_SOURCES
    return _payload_bool(data, "reply_to_qq", default)


async def _maybe_forward_reply_to_qq(data: dict[str, Any], query: str, reply: str) -> dict[str, Any] | None:
    if not _should_forward_reply_to_qq(data):
        return None
    message = f"[VoCat]\n你说：{query}\n回复：{reply}"
    return await send_private_msg_async(VOCAT_QQ_FORWARD_USER_ID, message, quiet=True)


def _with_expression(result: dict[str, Any]) -> dict[str, Any]:
    reply = str(result.get("reply", "") or "")
    query = str(result.get("query", "") or "")
    explicit_expression = result.get("expression")
    if explicit_expression:
        result["expression"] = normalize_vocat_expression(explicit_expression)
    else:
        result["expression"] = select_vocat_expression(query or reply)
    print(
        f"[VOCAT] expression source={result.get('source', '')} "
        f"expression={result['expression']} query={_preview(query)!r} reply={_preview(reply)!r}"
    )
    return result


# _handle_local_skill_sync：处理本地技能同步
def _handle_local_skill_sync(query: str) -> dict[str, Any] | None:
    expression_result = _detect_expression_query(query)
    if expression_result is not None:
        return expression_result

    md_path = _extract_md_path(query)
    if md_path is not None:
        return {
            "handled": True,
            "source": "local_markdown",
            "reply": _read_markdown_file(md_path),
            "expression": "blink",
        }

    weather_reply = handle_weather_query(query)
    if weather_reply:
        return {
            "handled": True,
            "source": "local_weather",
            "reply": weather_reply,
            "expression": "blink",
        }

    schedule_intent = detect_schedule_intent(query)
    if schedule_intent == "today_schedule":
        return {
            "handled": True,
            "source": "local_schedule",
            "reply": format_today_schedule_reply(query_today_schedule(SCHEDULE_PATH)),
            "expression": "happy",
        }
    if schedule_intent == "tomorrow_schedule":
        return {
            "handled": True,
            "source": "local_schedule",
            "reply": format_tomorrow_schedule_reply(query_tomorrow_schedule(SCHEDULE_PATH)),
            "expression": "happy",
        }

    normalized = query.strip()
    if normalized.startswith(("agent ", "/agent ", "browser ", "/browser ")):
        return {
            "handled": True,
            "source": "local_agent_background",
            "reply": "我已经开始处理这个系统代理任务，完成后会主动播报结果。",
            "expression": "dizzy",
            "background": True,
            "background_kind": "pc_agent",
        }

    return None


# _run_pc_agent_background：运行电脑Agent后台
async def _run_pc_agent_background(query: str) -> None:
    result = await asyncio.to_thread(handle_pc_agent_command, OWNER_QQ, query)
    if isinstance(result, dict):
        summary = result.get("message") or result.get("reply") or str(result)
    else:
        summary = str(result)
    await send_tts_vocal(summary[:300] or "任务已经完成。")


# _submit_background_job：后台任务处理
def _submit_background_job(kind: str, query: str) -> None:
    if kind == "pc_agent":
        _VOCAT_EXECUTOR.submit(asyncio.run, _run_pc_agent_background(query))


# process_vocat_query：处理VoCat查询
async def process_vocat_query(data: dict[str, Any]) -> dict[str, Any]:
    """Process a VoCat webhook request."""
    query = _extract_query(data)
    if not query:
        return {"ok": False, "error": "missing_query"}

    local_result = await asyncio.to_thread(_handle_local_skill_sync, query)
    if local_result:
        if local_result.get("background"):
            _submit_background_job(local_result["background_kind"], query)
        qq_result = await _maybe_forward_reply_to_qq(data, query, str(local_result.get("reply", "")))
        result = {"ok": True, **local_result, "query": query}
        if qq_result is not None:
            result["qq_result"] = qq_result
        return _with_expression(result)

    if _is_qq_forward_query(query):
        send_result = await send_private_msg_async(
            VOCAT_QQ_FORWARD_USER_ID,
            f"[VoCat] {query}",
            quiet=True,
        )
        return _with_expression({
            "ok": True,
            "handled": True,
            "source": "qq_forward",
            "reply": "我已经把这条消息转发到 QQ 了。",
            "qq_result": send_result,
            "query": query,
        })

    llm_reply = await call_kimi_text_async(query)
    qq_result = await _maybe_forward_reply_to_qq(data, query, llm_reply)
    result = {
        "ok": True,
        "handled": True,
        "source": "kimi",
        "reply": llm_reply,
        "query": query,
    }
    if qq_result is not None:
        result["qq_result"] = qq_result
    return _with_expression(result)


# maybe_handle_vocat_remote_command：处理VoCat遥控命令
async def maybe_handle_vocat_remote_command(user_id: int | None, query: str) -> dict[str, Any] | None:
    """Handle QQ side remote control commands for the VoCat hardware."""
    if user_id is None or user_id not in VOCAT_REMOTE_CONTROL_USERS:
        return None

    stripped = (query or "").strip()
    if not stripped:
        return None

    expression_match = re.fullmatch(r"#表情\s+(.+)", stripped)
    if expression_match:
        expression_id = expression_match.group(1).strip()
        try:
            result = await send_expression(expression_id)
        except VocatControllerError as exc:
            return {
                "handled": True,
                "reply": f"VoCat 表情控制失败：{exc}",
                "result": {"ok": False, "error": str(exc)},
            }
        return {
            "handled": True,
            "reply": f"已触发 VoCat 表情：{expression_id}",
            "result": result,
        }

    tts_match = re.fullmatch(r"#说\s+(.+)", stripped)
    if tts_match:
        text = tts_match.group(1).strip()
        try:
            result = await send_tts_vocal(text)
        except VocatControllerError as exc:
            return {
                "handled": True,
                "reply": f"VoCat 播报失败：{exc}",
                "result": {"ok": False, "error": str(exc)},
            }
        return {
            "handled": True,
            "reply": f"已让 VoCat 播报：{text[:40]}",
            "result": result,
        }

    return None
