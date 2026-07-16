import base64
import mimetypes
import os
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Optional
from urllib.parse import urlparse

import requests
from PIL import Image


def build_vision_prompt(user_text: str) -> str:
    text = str(user_text or "").strip()
    if not text:
        return (
            "按三段式输出："
            "1) 客观识别一句（只说看到的内容）；"
            "2) 群聊口语短句（可选，不超过12字）；"
            "3) 若不确定请明确写“我不确定”。"
            "禁止模板化夸夸，如“哈哈/太可爱了/萌翻了”连发。"
        )
    return (
        "先按用户要求答。"
        "输出优先三段式：客观识别一句 + 可选口语短句 + 不确定性声明。"
        "如果用户要识别文字，就直接提取文字，识别不清就明确不确定。"
        "禁止固定夸夸模板（哈哈/好可爱/萌翻）。"
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

    prepared_image_path = image_path
    cleanup_prepared_file = False
    def _finish(result: VisionResult) -> VisionResult:
        if cleanup_prepared_file:
            _safe_remove_file(prepared_image_path)
        return result
    try:
        prepared_image_path, cleanup_prepared_file = _prepare_image_for_vision(image_path)
    except Exception:
        prepared_image_path = image_path
        cleanup_prepared_file = False

    try:
        payload = _build_request_payload(prepared_image_path, user_text=user_text, model=model)
    except Exception as exc:  # pragma: no cover - filesystem/runtime dependent
        return _finish(VisionResult(
            **{**base_result.__dict__, "status": "request_build_failed", "error": str(exc), "traceback": traceback.format_exc()},
        ))

    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }

    try:
        resp = requests.post(api_url, json=payload, headers=headers, timeout=60)
    except requests.RequestException as exc:
        return _finish(VisionResult(
            **{**base_result.__dict__, "status": "network_error", "error": str(exc), "traceback": traceback.format_exc()},
        ))
    except Exception as exc:  # pragma: no cover - defensive fallback
        return _finish(VisionResult(
            **{**base_result.__dict__, "status": "unknown_error", "error": str(exc), "traceback": traceback.format_exc()},
        ))

    response_preview = (resp.text or "")[:500]
    if resp.status_code in (401, 403):
        return _finish(VisionResult(
            **{
                **base_result.__dict__,
                "status": "auth_failed",
                "http_status": resp.status_code,
                "response_preview": response_preview,
                "error": f"http {resp.status_code}",
            },
        ))
    if resp.status_code == 404:
        return _finish(VisionResult(
            **{
                **base_result.__dict__,
                "status": "endpoint_not_found",
                "http_status": resp.status_code,
                "response_preview": response_preview,
                "error": "http 404",
            },
        ))
    if not resp.ok:
        lowered = response_preview.lower()
        status = "request_failed"
        if _looks_like_model_not_vision_capable(lowered):
            status = "model_unsupported"
        elif _looks_like_image_url_unreachable(lowered):
            status = "image_url_unreachable"
        return _finish(VisionResult(
            **{
                **base_result.__dict__,
                "status": status,
                "http_status": resp.status_code,
                "response_preview": response_preview,
                "error": f"http {resp.status_code}",
            },
        ))

    try:
        data = resp.json()
    except ValueError as exc:
        return _finish(VisionResult(
            **{
                **base_result.__dict__,
                "status": "response_parse_failed",
                "http_status": resp.status_code,
                "response_preview": response_preview,
                "error": str(exc),
                "traceback": traceback.format_exc(),
            },
        ))

    content = _extract_response_text(data)
    if not content:
        return _finish(VisionResult(
            **{
                **base_result.__dict__,
                "status": "response_parse_failed",
                "http_status": resp.status_code,
                "response_preview": response_preview,
                "error": "response text extraction returned empty content",
            },
        ))
    result = VisionResult(
        **{
            **base_result.__dict__,
            "status": "ok",
            "content": content,
            "http_status": resp.status_code,
            "response_preview": response_preview,
        },
    )
    return _finish(result)


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

    return {
        "contents": [
            {
                "role": "user",
                "parts": [
                    {"text": build_vision_prompt(user_text)},
                    {
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": encoded,
                        }
                    },
                ],
            }
        ],
    }


def _prepare_image_for_vision(image_path: str) -> tuple[str, bool]:
    """
    Normalize any input image into a JPEG first frame.
    This avoids provider-side media-type incompatibilities for gifs/webp variants.
    Returns (path, should_cleanup).
    """
    with Image.open(image_path) as img:
        # Always use the first frame; animated assets are downgraded to static snapshot.
        try:
            img.seek(0)
        except Exception:
            pass
        rgb = img.convert("RGB")
        target_path = _build_prepared_image_path(image_path)
        rgb.save(target_path, format="JPEG", quality=92)
    return target_path, True


def _build_prepared_image_path(source_path: str) -> str:
    base_dir = os.path.dirname(source_path) or "."
    return os.path.join(base_dir, f"{uuid.uuid4().hex}-vision.jpg")


def _safe_remove_file(path: str) -> None:
    try:
        os.remove(path)
    except Exception:
        pass


def _extract_response_text(data) -> str:
    if not isinstance(data, dict):
        return ""

    if isinstance(data.get("reply"), str):
        return data.get("reply", "").strip()
    if isinstance(data.get("text"), str):
        return data.get("text", "").strip()

    candidates = data.get("candidates")
    if isinstance(candidates, list):
        parts = []
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            content = candidate.get("content")
            if not isinstance(content, dict):
                continue
            for item in content.get("parts") or []:
                if not isinstance(item, dict):
                    continue
                text = str(item.get("text") or "").strip()
                if text:
                    parts.append(text)
        if parts:
            return " ".join(parts).strip()

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
