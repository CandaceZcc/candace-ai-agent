"""LLM client helpers."""

import asyncio
import json
import subprocess
import time
from typing import Any

import requests

from apps.qq_ai_bridge.config.settings import AI_CMD
from apps.qq_ai_bridge.config.settings import (
    KIMI_API_KEY,
    KIMI_BASE_URL,
    KIMI_MODEL,
    KIMI_TIMEOUT_SECONDS,
)


def _extract_output_and_usage(raw_output: str) -> tuple[str, dict[str, Any] | None]:
    """Try to parse CLI JSON output without breaking plain-text responses."""
    stripped = (raw_output or "").strip()
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


def call_ai(text: str, metadata: dict[str, Any] | None = None) -> str:
    """Call the local LLM CLI and return text output."""
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
        result = subprocess.check_output(
            [AI_CMD, text],
            stderr=subprocess.STDOUT,
            timeout=180,
        )
        raw_output = result.decode("utf-8", errors="ignore")
        output, usage = _extract_output_and_usage(raw_output)

        if not output:
            output = "ocai 没有返回内容。"

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
        output = e.output.decode("utf-8", errors="ignore")
        print(f"[OCAI] error user_id={user_id} duration_ms={duration_ms} type=CalledProcessError")
        print(f"[OCAI] CalledProcessError:\n{output}")
        return f"ocai 调用失败：\n{output}"
    except subprocess.TimeoutExpired:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        print(f"[OCAI] timeout user_id={user_id} duration_ms={duration_ms}")
        return "ocai 处理超时。"
    except FileNotFoundError:
        print(f"[OCAI] 找不到命令: {AI_CMD}")
        return f"找不到 ocai 命令：{AI_CMD}"
    except Exception as e:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        print(f"[OCAI] exception user_id={user_id} duration_ms={duration_ms} error={e}")
        return f"发生错误：{e}"


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


def call_kimi_text(prompt: str, system_prompt: str | None = None, timeout_seconds: int | None = None) -> str:
    """Call Kimi chat completions and return plain text output."""
    if not KIMI_API_KEY:
        return "Kimi API 未配置。请设置 KIMI_API_KEY。"

    timeout_seconds = timeout_seconds or KIMI_TIMEOUT_SECONDS
    url = f"{KIMI_BASE_URL.rstrip('/')}/chat/completions"
    headers = {
        "Authorization": f"Bearer {KIMI_API_KEY}",
        "Content-Type": "application/json",
    }
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
        response = requests.post(url, headers=headers, json=payload, timeout=timeout_seconds)
        response.raise_for_status()
        data = response.json()
        text = _extract_kimi_text(data)
        duration_ms = int((time.monotonic() - started_at) * 1000)
        usage = data.get("usage") if isinstance(data, dict) else {}
        print(
            "[KIMI] success"
            f" duration_ms={duration_ms}"
            f" prompt_tokens={usage.get('prompt_tokens', 'na') if isinstance(usage, dict) else 'na'}"
            f" completion_tokens={usage.get('completion_tokens', 'na') if isinstance(usage, dict) else 'na'}"
            f" total_tokens={usage.get('total_tokens', 'na') if isinstance(usage, dict) else 'na'}"
        )
        return text or "Kimi 没有返回内容。"
    except requests.RequestException as exc:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        print(f"[KIMI] request_error duration_ms={duration_ms} error={exc}")
        return f"Kimi 调用失败：{exc}"
    except Exception as exc:
        duration_ms = int((time.monotonic() - started_at) * 1000)
        print(f"[KIMI] exception duration_ms={duration_ms} error={exc}")
        return f"Kimi 处理失败：{exc}"


async def call_kimi_text_async(
    prompt: str,
    system_prompt: str | None = None,
    timeout_seconds: int | None = None,
) -> str:
    """Async wrapper for Kimi text generation."""
    return await asyncio.to_thread(call_kimi_text, prompt, system_prompt, timeout_seconds)
