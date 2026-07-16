"""RightCodes asynchronous image-generation helpers."""

from __future__ import annotations

import base64
import io
import re
import time
from dataclasses import dataclass
from typing import Callable

import requests
from PIL import Image

from apps.qq_ai_bridge.config.settings import (
    DRAW_API_KEY,
    DRAW_ASPECT_RATIO,
    DRAW_BASE_URL,
    DRAW_FALLBACK_ENABLED,
    DRAW_FALLBACK_MODEL,
    DRAW_IMAGE_SIZE,
    DRAW_MODEL,
    DRAW_POLL_MAX_TRANSIENT_ERRORS,
    DRAW_POLL_INTERVAL_SECONDS,
    DRAW_TIMEOUT_SECONDS,
)
from apps.qq_ai_bridge.logging.bridge_log import log_event, log_warn

_PENDING_STATUSES = {"queued", "pending", "processing", "running", "in_progress"}
_TRANSIENT_HTTP_STATUSES = {408, 409, 425, 429}
_IMAGE_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)


@dataclass
class DrawResult:
    status: str
    task_id: str = ""
    image_url: str = ""
    error: str = ""
    http_status: int | None = None


def build_draw_payload(
    prompt: str,
    *,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    reference_image_data: str = "",
    reference_mime_type: str = "image/jpeg",
) -> dict:
    parts: list[dict] = [{"text": str(prompt or "").strip()}]
    if reference_image_data:
        parts.append(
            {
                "inline_data": {
                    "mime_type": reference_mime_type or "image/jpeg",
                    "data": reference_image_data,
                }
            }
        )
    return {
        "async": True,
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "imageConfig": {
                "aspectRatio": aspect_ratio,
                "imageSize": image_size,
            }
        },
    }


def build_images_payload(
    prompt: str,
    *,
    model: str,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    reference_image_data: str = "",
    reference_mime_type: str = "image/jpeg",
) -> dict:
    payload = {
        "model": str(model or "").strip(),
        "prompt": str(prompt or "").strip(),
        "n": 1,
        "size": aspect_ratio,
        "imageSize": image_size,
        "async": True,
    }
    if reference_image_data:
        mime_type = reference_mime_type or "image/jpeg"
        payload["image"] = [f"data:{mime_type};base64,{reference_image_data}"]
    return payload


def submit_draw(
    prompt: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    reference_image_data: str = "",
    reference_mime_type: str = "image/jpeg",
) -> DrawResult:
    if not str(api_key or "").strip():
        return DrawResult(status="config_missing", error="draw api key is missing")
    if not str(prompt or "").strip():
        return DrawResult(status="invalid_prompt", error="draw prompt is empty")

    url = (
        f"{str(base_url or '').rstrip('/')}"
        f"/draw/v1beta/models/{str(model or '').strip()}:generateContent"
    )
    payload = build_draw_payload(
        prompt,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        reference_image_data=reference_image_data,
        reference_mime_type=reference_mime_type,
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
    except requests.RequestException as exc:
        return DrawResult(status="network_error", error=str(exc))
    if not response.ok:
        return DrawResult(
            status="request_failed",
            error=f"http {response.status_code}",
            http_status=response.status_code,
        )
    try:
        data = response.json()
    except ValueError:
        return DrawResult(
            status="response_parse_failed",
            error="draw submit response is not json",
            http_status=response.status_code,
        )
    task_id = str(data.get("task_id") or "").strip() if isinstance(data, dict) else ""
    if not task_id:
        return DrawResult(
            status="response_parse_failed",
            error="draw submit response has no task id",
            http_status=response.status_code,
        )
    return DrawResult(status="submitted", task_id=task_id, http_status=response.status_code)


def submit_images_draw(
    prompt: str,
    *,
    api_key: str,
    base_url: str,
    model: str,
    aspect_ratio: str = "1:1",
    image_size: str = "1K",
    reference_image_data: str = "",
    reference_mime_type: str = "image/jpeg",
) -> DrawResult:
    if not str(api_key or "").strip():
        return DrawResult(status="config_missing", error="draw api key is missing")
    if not str(prompt or "").strip():
        return DrawResult(status="invalid_prompt", error="draw prompt is empty")
    if not str(model or "").strip():
        return DrawResult(status="config_missing", error="fallback draw model is missing")

    url = f"{str(base_url or '').rstrip('/')}/draw/v1/images/generations"
    payload = build_images_payload(
        prompt,
        model=model,
        aspect_ratio=aspect_ratio,
        image_size=image_size,
        reference_image_data=reference_image_data,
        reference_mime_type=reference_mime_type,
    )
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=60)
    except requests.RequestException as exc:
        return DrawResult(status="network_error", error=str(exc))
    if not response.ok:
        return DrawResult(
            status="request_failed",
            error=f"http {response.status_code}",
            http_status=response.status_code,
        )
    try:
        data = response.json()
    except ValueError:
        return DrawResult(
            status="response_parse_failed",
            error="draw submit response is not json",
            http_status=response.status_code,
        )
    task_id = str(data.get("task_id") or "").strip() if isinstance(data, dict) else ""
    if not task_id:
        return DrawResult(
            status="response_parse_failed",
            error="draw submit response has no task id",
            http_status=response.status_code,
        )
    return DrawResult(status="submitted", task_id=task_id, http_status=response.status_code)


def poll_draw(
    task_id: str,
    *,
    api_key: str,
    base_url: str,
    timeout_seconds: int,
    poll_interval_seconds: int,
    max_transient_errors: int = 6,
    provider: str = "draw",
    model: str = "",
    should_log: bool = False,
    now_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> DrawResult:
    started_at = now_fn()
    url = f"{str(base_url or '').rstrip('/')}/v1/tasks/{task_id}"
    headers = {"Authorization": f"Bearer {api_key}"}
    consecutive_transient_errors = 0
    last_status = ""

    while True:
        if now_fn() - started_at >= timeout_seconds:
            if should_log:
                log_warn(
                    "DRAW",
                    "poll timeout provider=%s model=%s task=%s",
                    provider,
                    model,
                    _short_task_id(task_id),
                )
            return DrawResult(status="timeout", task_id=task_id, error="draw task timed out")
        try:
            response = requests.get(url, headers=headers, timeout=30)
        except requests.RequestException as exc:
            consecutive_transient_errors += 1
            if should_log:
                log_warn(
                    "DRAW",
                    "poll transient provider=%s model=%s task=%s error_type=%s retry=%s/%s",
                    provider,
                    model,
                    _short_task_id(task_id),
                    type(exc).__name__,
                    consecutive_transient_errors,
                    max_transient_errors,
                )
            if consecutive_transient_errors > max_transient_errors:
                return DrawResult(status="network_error", task_id=task_id, error=str(exc))
            sleep_fn(poll_interval_seconds)
            continue
        if not response.ok:
            if _is_transient_http_status(response.status_code):
                consecutive_transient_errors += 1
                if should_log:
                    log_warn(
                        "DRAW",
                        "poll transient provider=%s model=%s task=%s http=%s retry=%s/%s",
                        provider,
                        model,
                        _short_task_id(task_id),
                        response.status_code,
                        consecutive_transient_errors,
                        max_transient_errors,
                    )
                if consecutive_transient_errors <= max_transient_errors:
                    sleep_fn(poll_interval_seconds)
                    continue
            return DrawResult(
                status="request_failed",
                task_id=task_id,
                error=f"http {response.status_code}",
                http_status=response.status_code,
            )
        consecutive_transient_errors = 0
        try:
            data = response.json()
        except ValueError:
            return DrawResult(
                status="response_parse_failed",
                task_id=task_id,
                error="draw task response is not json",
                http_status=response.status_code,
            )

        image_url = _extract_image_url(data)
        if image_url:
            return DrawResult(
                status="completed",
                task_id=task_id,
                image_url=image_url,
                http_status=response.status_code,
            )

        status = str(data.get("status") or "").strip().lower() if isinstance(data, dict) else ""
        if should_log and status and status != last_status:
            log_event(
                "DRAW",
                "poll state provider=%s model=%s task=%s status=%s",
                provider,
                model,
                _short_task_id(task_id),
                status,
            )
            last_status = status
        if status == "failed":
            error = data.get("error") if isinstance(data, dict) else None
            message = error.get("message") if isinstance(error, dict) else error
            return DrawResult(
                status="failed",
                task_id=task_id,
                error=str(message or "draw task failed"),
                http_status=response.status_code,
            )
        if status == "completed":
            return DrawResult(
                status="response_parse_failed",
                task_id=task_id,
                error="completed draw task has no image url",
                http_status=response.status_code,
            )
        if status and status not in _PENDING_STATUSES:
            return DrawResult(
                status="response_parse_failed",
                task_id=task_id,
                error=f"unknown draw task status: {status}",
                http_status=response.status_code,
            )
        sleep_fn(poll_interval_seconds)


def _is_transient_http_status(status_code: int) -> bool:
    return status_code in _TRANSIENT_HTTP_STATUSES or status_code >= 500


def _short_task_id(task_id: str) -> str:
    value = str(task_id or "").strip()
    if len(value) <= 14:
        return value
    return f"{value[:7]}…{value[-6:]}"


def generate_image(prompt: str, reference_image_url: str = "") -> DrawResult:
    reference_data = ""
    reference_mime_type = "image/jpeg"
    if reference_image_url:
        prepared = _download_reference_image(reference_image_url)
        if isinstance(prepared, DrawResult):
            return prepared
        reference_data, reference_mime_type = prepared

    primary = submit_draw(
        prompt,
        api_key=DRAW_API_KEY,
        base_url=DRAW_BASE_URL,
        model=DRAW_MODEL,
        aspect_ratio=DRAW_ASPECT_RATIO,
        image_size=DRAW_IMAGE_SIZE,
        reference_image_data=reference_data,
        reference_mime_type=reference_mime_type,
    )
    log_event(
        "DRAW",
        "submit provider=gemini model=%s status=%s task=%s reference=%s",
        DRAW_MODEL,
        primary.status,
        _short_task_id(primary.task_id),
        bool(reference_data),
    )
    if primary.status == "submitted":
        primary = poll_draw(
            primary.task_id,
            api_key=DRAW_API_KEY,
            base_url=DRAW_BASE_URL,
            timeout_seconds=DRAW_TIMEOUT_SECONDS,
            poll_interval_seconds=DRAW_POLL_INTERVAL_SECONDS,
            max_transient_errors=DRAW_POLL_MAX_TRANSIENT_ERRORS,
            provider="gemini",
            model=DRAW_MODEL,
            should_log=True,
        )
    log_event(
        "DRAW",
        "result provider=gemini model=%s status=%s task=%s http=%s",
        DRAW_MODEL,
        primary.status,
        _short_task_id(primary.task_id),
        primary.http_status,
    )
    if primary.status == "completed" or not DRAW_FALLBACK_ENABLED:
        return primary
    if primary.status in {"config_missing", "invalid_prompt", "reference_image_failed"}:
        return primary

    fallback = submit_images_draw(
        prompt,
        api_key=DRAW_API_KEY,
        base_url=DRAW_BASE_URL,
        model=DRAW_FALLBACK_MODEL,
        aspect_ratio=DRAW_ASPECT_RATIO,
        image_size=DRAW_IMAGE_SIZE,
        reference_image_data=reference_data,
        reference_mime_type=reference_mime_type,
    )
    log_event(
        "DRAW",
        "fallback provider=images model=%s reason=%s status=%s task=%s",
        DRAW_FALLBACK_MODEL,
        primary.status,
        fallback.status,
        _short_task_id(fallback.task_id),
    )
    if fallback.status != "submitted":
        return fallback
    fallback = poll_draw(
        fallback.task_id,
        api_key=DRAW_API_KEY,
        base_url=DRAW_BASE_URL,
        timeout_seconds=DRAW_TIMEOUT_SECONDS,
        poll_interval_seconds=DRAW_POLL_INTERVAL_SECONDS,
        max_transient_errors=DRAW_POLL_MAX_TRANSIENT_ERRORS,
        provider="images",
        model=DRAW_FALLBACK_MODEL,
        should_log=True,
    )
    log_event(
        "DRAW",
        "result provider=images model=%s status=%s task=%s http=%s",
        DRAW_FALLBACK_MODEL,
        fallback.status,
        _short_task_id(fallback.task_id),
        fallback.http_status,
    )
    return fallback


def _download_reference_image(image_url: str) -> tuple[str, str] | DrawResult:
    try:
        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        with Image.open(io.BytesIO(response.content)) as image:
            output = io.BytesIO()
            image.convert("RGB").save(output, format="JPEG", quality=92)
    except (requests.RequestException, OSError) as exc:
        return DrawResult(status="reference_image_failed", error=str(exc))
    return base64.b64encode(output.getvalue()).decode("utf-8"), "image/jpeg"


def _extract_image_url(data: object) -> str:
    if not isinstance(data, dict):
        return ""
    images = data.get("data")
    if isinstance(images, list):
        for item in images:
            if isinstance(item, dict) and str(item.get("url") or "").strip():
                return str(item["url"]).strip()

    candidates = data.get("candidates")
    if isinstance(candidates, list):
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            for part in content.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                match = _IMAGE_URL_RE.search(str(part.get("text") or ""))
                if match:
                    return match.group(0).rstrip(".,，。！？!?)）]")
    return ""
