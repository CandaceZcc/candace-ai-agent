"""LLM client helpers."""

import asyncio
import json
import re
import subprocess
import threading
import time
from typing import Any

import requests
from apps.qq_ai_bridge.config.settings import (
    AI_CMD,
    KIMI_API_KEY,
    KIMI_BASE_URL,
    KIMI_MODEL,
    KIMI_TIMEOUT_SECONDS,
    LLM_BACKEND,
    LLM_MAX_CONCURRENCY,
    LLM_QUEUE_TIMEOUT_SECONDS,
)

_ANSI_ESCAPE_RE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OPENCLAW_DIAGNOSTIC_TOKENS = (
    "[plugins]",
    "plugins.allow is empty",
    "discovered non-bundled plugins may auto-load",
    "To trust them explicitly, set plugins.allow",
)
_LOCAL_DIAGNOSTIC_TOKENS = (
    "/home/",
    ".openclaw",
    "node_modules",
)
_HTTP_SESSION = requests.Session()
_LLM_SEMAPHORE = threading.BoundedSemaphore(LLM_MAX_CONCURRENCY)
_LLM_BUSY_REPLY = "当前模型请求较多，请稍后再试。"


def _strip_cli_diagnostics(raw_output: str) -> str:
    """Remove local CLI diagnostics that should never become QQ replies."""
    cleaned = _ANSI_ESCAPE_RE.sub("", str(raw_output or ""))
    cleaned = cleaned.replace("\r\n", "\n").replace("\r", "\n")
    lines: list[str] = []
    for line in cleaned.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _is_cli_diagnostic_line(stripped):
            continue
        lines.append(stripped)
    return "\n".join(lines).strip()


def _is_cli_diagnostic_line(line: str) -> bool:
    normalized = line.strip()
    if not normalized:
        return True
    if any(token in normalized for token in _OPENCLAW_DIAGNOSTIC_TOKENS):
        return True
    if any(token in normalized for token in _LOCAL_DIAGNOSTIC_TOKENS) and (
        "openclaw" in normalized.lower() or "plugin" in normalized.lower()
    ):
        return True
    return False


def _extract_output_and_usage(raw_output: str) -> tuple[str, dict[str, Any] | None]:
    """Try to parse CLI JSON output without breaking plain-text responses."""
    stripped = _strip_cli_diagnostics(raw_output)
    if not stripped:
        return "", None

    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError:
        return stripped, None

    if isinstance(payload, dict):
        usage = payload.get("usage")
        for key in ("output", "text", "response", "content"):
            value = payload.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip(), usage if isinstance(usage, dict) else None
    return stripped, None


def _render_cli_prompt(value: str | list[dict[str, Any]]) -> str:
    if isinstance(value, str):
        return value
    lines: list[str] = []
    for message in value:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").strip() or "user"
        content = message.get("content", "")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _call_cli_llm(text: str | list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> str:
    """Call the compatibility OpenClaw CLI backend."""
    text = _render_cli_prompt(text)
    metadata = metadata or {}
    user_id = metadata.get("user_id", "unknown")
    merged_message_count = metadata.get("merged_message_count", "na")
    prompt_mode = metadata.get("prompt_mode", "na")
    query_len = metadata.get("query_len", len(text))
    history_chars = metadata.get("history_chars", "na")
    history_items = metadata.get("history_items", "na")
    instruction_chars = metadata.get("instruction_chars", "na")
    prompt_chars = metadata.get("prompt_chars", len(text))
    print(
        "[OCAI] start"
        f" user_id={user_id}"
        f" merged_message_count={merged_message_count}"
        f" prompt_mode={prompt_mode}"
        f" query_len={query_len}"
        f" history_chars={history_chars}"
        f" history_items={history_items}"
        f" instruction_chars={instruction_chars}"
        f" prompt_chars={prompt_chars}"
    )
    print(f"[OCAI] 参数前200字符: {text[:200]!r}")
    started_at = time.monotonic()

    try:
        result = subprocess.run(
            [AI_CMD, text],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=180,
            check=False,
            text=True,
            encoding="utf-8",
            errors="ignore",
        )
        raw_output = result.stdout or ""
        raw_error = result.stderr or ""
        output, usage = _extract_output_and_usage(raw_output)
        diagnostic_error = _strip_cli_diagnostics(raw_error)

        if result.returncode != 0:
            duration_ms = int((time.monotonic() - started_at) * 1000)
            print(
                "[OCAI] error"
                f" user_id={user_id}"
                f" duration_ms={duration_ms}"
                f" returncode={result.returncode}"
            )
            return ""

        if diagnostic_error:
            print(f"[OCAI] diagnostic stderr ignored chars={len(diagnostic_error)}")

        duration_ms = int((time.monotonic() - started_at) * 1000)
        prompt_tokens = "na"
        completion_tokens = "na"
        total_tokens = "na"
        if usage:
            prompt_tokens = usage.get("prompt_tokens", usage.get("input_tokens", "na"))
            completion_tokens = usage.get("completion_tokens", usage.get("output_tokens", "na"))
            total_tokens = usage.get("total_tokens", "na")
        print(
            "[OCAI] success"
            f" user_id={user_id}"
            f" merged_message_count={merged_message_count}"
            f" prompt_mode={prompt_mode}"
            f" duration_ms={duration_ms}"
            f" prompt_tokens={prompt_tokens}"
            f" completion_tokens={completion_tokens}"
            f" total_tokens={total_tokens}"
        )
        print(f"[OCAI] 输出前300字符:\n{output[:300]}")
        return output
    except subprocess.CalledProcessError as e:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        print(f"[OCAI] error user_id={user_id} duration_ms={duration_ms} type=CalledProcessError")
        return ""
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        print(f"[OCAI] timeout user_id={user_id} duration_ms={duration_ms}")
        return ""
    except FileNotFoundError:
        print(f"[OCAI] 找不到命令: {AI_CMD}")
        return ""
    except Exception as e:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        print(f"[OCAI] exception user_id={user_id} duration_ms={duration_ms} error={e}")
        return ""


def _extract_kimi_text(payload: dict[str, Any]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""

    first_choice = choices[0] or {}
    message = first_choice.get("message") or {}
    content = message.get("content")
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            text = item.get("text")
            if isinstance(text, str) and text.strip():
                parts.append(text.strip())
        return "\n".join(parts).strip()
    return ""


def _select_llm_backend(backend: str, *, api_key: str) -> str:
    normalized = str(backend or "auto").strip().lower()
    if normalized not in {"auto", "direct", "cli"}:
        normalized = "auto"
    if normalized == "auto":
        return "direct" if str(api_key or "").strip() else "cli"
    return normalized


def _acquire_llm_slot() -> bool:
    if LLM_QUEUE_TIMEOUT_SECONDS <= 0:
        return _LLM_SEMAPHORE.acquire(blocking=False)
    return _LLM_SEMAPHORE.acquire(timeout=LLM_QUEUE_TIMEOUT_SECONDS)


def _call_direct_llm(
    prompt: str | list[dict[str, Any]],
    *,
    system_prompt: str | None = None,
    timeout_seconds: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> str:
    if not KIMI_API_KEY:
        return "文本模型 API 未配置，请设置 KIMI_API_KEY。"

    metadata = metadata or {}
    timeout = timeout_seconds or KIMI_TIMEOUT_SECONDS
    url = f"{KIMI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {KIMI_API_KEY}",
        "Content-Type": "application/json",
    }
    if isinstance(prompt, list):
        messages = [dict(message) for message in prompt if isinstance(message, dict)]
        if system_prompt:
            messages.insert(0, {"role": "system", "content": system_prompt})
    else:
        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
    payload = {
        "model": KIMI_MODEL,
        "messages": messages,
        "temperature": 0.3,
    }

    started_at = time.monotonic()
    try:
        for attempt in range(1, 3):
            response = _HTTP_SESSION.post(
                url,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()
            data = response.json()
            output = _extract_kimi_text(data)
            duration_ms = int((time.monotonic() - started_at) * 1000)
            usage = data.get("usage") if isinstance(data, dict) else {}
            prompt_tokens = usage.get("prompt_tokens", "na") if isinstance(usage, dict) else "na"
            completion_tokens = usage.get("completion_tokens", "na") if isinstance(usage, dict) else "na"
            total_tokens = usage.get("total_tokens", "na") if isinstance(usage, dict) else "na"
            if output:
                print(
                    "[LLM] success"
                    " backend=direct"
                    f" model={KIMI_MODEL}"
                    f" user_id={metadata.get('user_id', 'unknown')}"
                    f" duration_ms={duration_ms}"
                    f" attempt={attempt}"
                    f" prompt_tokens={prompt_tokens}"
                    f" completion_tokens={completion_tokens}"
                    f" total_tokens={total_tokens}"
                )
                return output
            print(
                "[LLM] empty_visible_content"
                " backend=direct"
                f" model={KIMI_MODEL}"
                f" user_id={metadata.get('user_id', 'unknown')}"
                f" duration_ms={duration_ms}"
                f" attempt={attempt}"
                f" prompt_tokens={prompt_tokens}"
                f" completion_tokens={completion_tokens}"
                f" total_tokens={total_tokens}"
            )
        return ""
    except requests.RequestException as exc:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        status_code = getattr(getattr(exc, "response", None), "status_code", "na")
        print(
            "[LLM] request_error"
            " backend=direct"
            f" model={KIMI_MODEL}"
            f" duration_ms={duration_ms}"
            f" status_code={status_code}"
            f" error_type={type(exc).__name__}"
        )
        return ""
    except Exception as exc:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        print(
            "[LLM] exception"
            " backend=direct"
            f" model={KIMI_MODEL}"
            f" duration_ms={duration_ms}"
            f" error_type={type(exc).__name__}"
        )
        return ""


def call_ai(text: str | list[dict[str, Any]], metadata: dict[str, Any] | None = None) -> str:
    """Call the configured text-model backend with bounded concurrency."""
    if not _acquire_llm_slot():
        print("[LLM] busy queue_timeout")
        return _LLM_BUSY_REPLY
    try:
        backend = _select_llm_backend(LLM_BACKEND, api_key=KIMI_API_KEY)
        if backend == "direct":
            return _call_direct_llm(text, metadata=metadata)
        return _call_cli_llm(text, metadata=metadata)
    finally:
        _LLM_SEMAPHORE.release()


def call_kimi_text(
    prompt: str,
    system_prompt: str | None = None,
    timeout_seconds: int | None = None,
) -> str:
    """Compatibility wrapper for direct OpenAI-compatible text generation."""
    if not KIMI_API_KEY:
        return "Kimi API 未配置。请设置 KIMI_API_KEY。"
    if not _acquire_llm_slot():
        return _LLM_BUSY_REPLY
    try:
        return _call_direct_llm(
            prompt,
            system_prompt=system_prompt,
            timeout_seconds=timeout_seconds,
            metadata={"user_id": "compat_text"},
        )
    finally:
        _LLM_SEMAPHORE.release()


async def call_kimi_text_async(
    prompt: str,
    system_prompt: str | None = None,
    timeout_seconds: int | None = None,
) -> str:
    """Async wrapper for Kimi text generation."""
    return await asyncio.to_thread(call_kimi_text, prompt, system_prompt, timeout_seconds)
