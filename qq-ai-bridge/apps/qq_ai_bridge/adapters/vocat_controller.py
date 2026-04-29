"""VoCat hardware remote controller backed by VolcEngine REST APIs."""

from __future__ import annotations

import asyncio
from typing import Any

import requests

from apps.qq_ai_bridge.config.settings import (
    VOCAT_API_TOKEN,
    VOCAT_BOT_ID,
    VOCAT_CONTROL_TIMEOUT_SECONDS,
    VOCAT_DEVICE_NAME,
    VOCAT_EXPRESSION_API_URL,
    VOCAT_INSTANCE_ID,
    VOCAT_PRODUCT_KEY,
    VOCAT_TTS_API_URL,
)
from apps.qq_ai_bridge.services.vocat_command_queue import (
    enqueue_vocat_expression,
    enqueue_vocat_tts,
)


class VocatControllerError(RuntimeError):
    """Raised when VoCat remote control API calls fail."""


def _build_headers() -> dict[str, str]:
    headers = {"Content-Type": "application/json"}
    if VOCAT_API_TOKEN:
        headers["Authorization"] = f"Bearer {VOCAT_API_TOKEN}"
    return headers


def _build_device_payload() -> dict[str, Any]:
    payload: dict[str, Any] = {}
    if VOCAT_INSTANCE_ID:
        payload["instance_id"] = VOCAT_INSTANCE_ID
    if VOCAT_PRODUCT_KEY:
        payload["product_key"] = VOCAT_PRODUCT_KEY
    if VOCAT_DEVICE_NAME:
        payload["device_name"] = VOCAT_DEVICE_NAME
    if VOCAT_BOT_ID:
        payload["bot_id"] = VOCAT_BOT_ID
    return payload


def _post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    if not url:
        raise VocatControllerError("VoCat API URL 未配置。")

    response = requests.post(
        url,
        headers=_build_headers(),
        json=payload,
        timeout=VOCAT_CONTROL_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    data = response.json() if response.content else {"ok": True}
    if isinstance(data, dict):
        status = data.get("status")
        success = data.get("success")
        if status in {"error", "failed"} or success is False:
            raise VocatControllerError(str(data))
    return data if isinstance(data, dict) else {"raw": data}


async def send_expression(expression_id: str | int) -> dict[str, Any]:
    """Ask the hardware to display a specific expression."""
    return await asyncio.to_thread(send_expression_sync, expression_id)


def send_expression_sync(expression_id: str | int) -> dict[str, Any]:
    """Ask the hardware to display a specific expression from sync contexts."""
    if not VOCAT_EXPRESSION_API_URL:
        return enqueue_vocat_expression(expression_id, source="bridge_expression_fallback")
    payload = {
        **_build_device_payload(),
        "expression_id": str(expression_id),
    }
    return _post_json(VOCAT_EXPRESSION_API_URL, payload)


async def send_tts_vocal(text: str) -> dict[str, Any]:
    """Ask the hardware to actively speak a text string."""
    return await asyncio.to_thread(send_tts_vocal_sync, text)


def send_tts_vocal_sync(text: str) -> dict[str, Any]:
    """Ask the hardware to actively speak a text string from sync contexts."""
    if not VOCAT_TTS_API_URL:
        return enqueue_vocat_tts(text, source="bridge_tts_fallback")
    payload = {
        **_build_device_payload(),
        "text": text.strip(),
    }
    return _post_json(VOCAT_TTS_API_URL, payload)
