import base64
import mimetypes
import os
import traceback
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import requests


def build_vision_prompt(user_text: str) -> str:
    text = str(user_text or "").strip()
    if not text:
        return "请简洁描述图片里有什么，语气自然，像聊天回复。"
    return (
        "请结合图片回答用户问题，回复简洁自然。"
        "如果用户是在问图片内容，就直接回答。"
        "如果用户要提取图中文字，就优先提取文字。"
        f"\n用户补充：{text}"
    )


@dataclass
class VisionResult:
    status: str
    content: str = ""
    request_url: str = ""
    model: str = ""
    input_image_count: int = 0
    input_image_urls: list[str] = field(default_factory=list)
    http_status: Optional[int] = None
    response_preview: str = ""
    error: str = ""
    traceback: str = ""


def read_vision_config() -> dict:
    return {
        "api_url": os.environ.get("VISION_API_URL", "").strip(),
        "api_key": os.environ.get("VISION_API_KEY", "").strip(),
        "model": os.environ.get("VISION_MODEL", "").strip(),
    }


def has_complete_vision_config() -> bool:
    cfg = read_vision_config()
    return bool(cfg["api_url"] and cfg["api_key"] and cfg["model"])


def analyze_image_with_details(
    image_path: str,
    user_text: str = "",
    input_image_urls: Optional[list[str]] = None,
) -> VisionResult:
    cfg = read_vision_config()
    api_url = cfg["api_url"]
    api_key = cfg["api_key"]
    model = cfg["model"]
    masked_url = _mask_url(api_url)
    image_urls = list(input_image_urls or [])

    base_result = VisionResult(
        status="unknown_error",
        request_url=masked_url,
        model=model,
        input_image_count=len(image_urls),
        input_image_urls=image_urls,
    )

    if not api_url or not api_key or not model:
        return VisionResult(
            status="config_missing",
            request_url=masked_url,
            model=model,
            input_image_count=len(image_urls),
            input_image_urls=image_urls,
            error="missing one or more required env vars: VISION_API_URL/VISION_API_KEY/VISION_MODEL",
        )

    try:
        payload = _build_request_payload(image_path, user_text=user_text, model=model)
    except Exception as exc:  # pragma: no cover - filesystem/runtime dependent
        return VisionResult(
            **{**base_result.__dict__, "status": "request_build_failed", "error": str(exc), "traceback": traceback.format_exc()},
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=60)
    except requests.RequestException as exc:
        return VisionResult(
            **{**base_result.__dict__, "status": "network_error", "error": str(exc), "traceback": traceback.format_exc()},
        )
    except Exception as exc:  # pragma: no cover - defensive fallback
        return VisionResult(
            **{**base_result.__dict__, "status": "unknown_error", "error": str(exc), "traceback": traceback.format_exc()},
        )

    response_preview = (resp.text or "")[:500]
    if resp.status_code in (401, 403):
        return VisionResult(
            **{
                **base_result.__dict__,
                "status": "auth_failed",
                "http_status": resp.status_code,
                "response_preview": response_preview,
                "error": f"http {resp.status_code}",
            },
        )
    if resp.status_code == 404:
        return VisionResult(
            **{
                **base_result.__dict__,
                "status": "endpoint_not_found",
                "http_status": resp.status_code,
                "response_preview": response_preview,
                "error": "http 404",
            },
        )
    if not resp.ok:
        lowered = response_preview.lower()
        status = "request_failed"
        if _looks_like_model_not_vision_capable(lowered):
            status = "model_unsupported"
        elif _looks_like_image_url_unreachable(lowered):
            status = "image_url_unreachable"
        return VisionResult(
            **{
                **base_result.__dict__,
                "status": status,
                "http_status": resp.status_code,
                "response_preview": response_preview,
                "error": f"http {resp.status_code}",
            },
        )

    try:
        data = resp.json()
    except ValueError as exc:
        return VisionResult(
            **{
                **base_result.__dict__,
                "status": "response_parse_failed",
                "http_status": resp.status_code,
                "response_preview": response_preview,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        )

    content = _extract_response_text(data)
    if not content:
        return VisionResult(
            **{
                **base_result.__dict__,
                "status": "response_parse_failed",
                "http_status": resp.status_code,
                "response_preview": response_preview,
                "error": "response text extraction returned empty content",
            },
        )
    return VisionResult(
        **{
            **base_result.__dict__,
            "status": "ok",
            "content": content,
            "http_status": resp.status_code,
            "response_preview": response_preview,
        },
    )


def analyze_image(image_path: str, user_text: str = "") -> str:
    result = analyze_image_with_details(image_path=image_path, user_text=user_text, input_image_urls=None)
    if result.status == "config_missing":
        return "识图功能还没配置好"
    if result.status != "ok":
        return "看图的时候出了点问题"
    return result.content or "我看了图，但暂时没整理出结果"


def _build_request_payload(image_path: str, user_text: str, model: str) -> dict:
    mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    image_url = f"data:{mime_type};base64,{encoded}"

    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是一个看图助手，回答要简短、自然、像聊天。"
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_vision_prompt(user_text)},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ]
    }


def _extract_response_text(data) -> str:
    if not isinstance(data, dict):
        return ""

    if isinstance(data.get("reply"), str):
        return data.get("reply", "").strip()
    if isinstance(data.get("text"), str):
        return data.get("text", "").strip()

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = str(item.get("text", "")).strip()
                    if text:
                        parts.append(text)
            return " ".join(parts).strip()

    return ""


def _mask_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _looks_like_model_not_vision_capable(text: str) -> bool:
    hints = (
        "does not support image",
        "does not support vision",
        "vision is not supported",
        "model_not_support",
        "invalid model",
        "multimodal",
        "image input is not enabled",
    )
    return any(hint in text for hint in hints)


def _looks_like_image_url_unreachable(text: str) -> bool:
    hints = (
        "image url",
        "cannot access image",
        "failed to download image",
        "invalid image url",
        "unable to fetch image",
    )
    return any(hint in text for hint in hints)
