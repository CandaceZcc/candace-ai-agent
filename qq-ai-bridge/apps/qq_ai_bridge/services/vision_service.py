"""Vision pipeline service for QQ bridge."""

import traceback
from typing import Iterable
from urllib.parse import urlparse

from apps.qq_ai_bridge.config.settings import IMAGE_TMP_DIR
from image_utils import download_image
from vision.client import analyze_image_with_details, read_vision_config

VISION_USER_FALLBACK = "我这边暂时看不了图，稍后再试试。"
VISION_USER_DOWNLOAD_FALLBACK = "这张图我暂时没拿到，麻烦稍后重发试试。"


def log_vision_config_status(log=print) -> None:
    cfg = read_vision_config()
    has_url = "set" if cfg["api_url"] else "missing"
    has_key = "set" if cfg["api_key"] else "missing"
    has_model = "set" if cfg["model"] else "missing"
    log(f"[VISION][CONFIG] VISION_API_URL={has_url}")
    log(f"[VISION][CONFIG] VISION_API_KEY={has_key}")
    log(f"[VISION][CONFIG] VISION_MODEL={has_model}")
    if "missing" in (has_url, has_key, has_model):
        log("[VISION][CONFIG] missing required vision config, image understanding will degrade gracefully")
    placeholders = _detect_placeholder_values(cfg)
    for item in placeholders:
        log(f"[VISION][CONFIG][WARNING] {item} is using a placeholder value and must be replaced with a real value")


def run_vision_pipeline(image_urls: str | Iterable[str], user_text: str, vision_log, save_dir=IMAGE_TMP_DIR) -> str:
    """Download an image, call the vision client, and return a short reply."""
    if isinstance(image_urls, str):
        urls = [image_urls] if image_urls else []
    else:
        urls = [u for u in list(image_urls or []) if u]

    vision_log(f"[VISION] image input count={len(urls)}")
    vision_log(f"[VISION] image URL list={urls}")
    if not urls:
        vision_log("[VISION][config_or_input] no usable absolute image URL")
        return VISION_USER_DOWNLOAD_FALLBACK

    first_url = urls[0]
    vision_log(f"[VISION] vision service called first_image_url={first_url}")

    try:
        local_path = download_image(first_url, save_dir=save_dir)
        vision_log(f"[VISION] download success: {local_path}")
    except Exception as exc:
        vision_log(f"[VISION][image_url_unreachable] download failed url={first_url} error={exc}")
        vision_log(f"[VISION][traceback] {traceback.format_exc()}")
        return VISION_USER_DOWNLOAD_FALLBACK

    cfg = read_vision_config()
    request_url = _mask_request_url(cfg["api_url"])
    model = cfg["model"]
    vision_log(f"[VISION] request_url={request_url}")
    vision_log(f"[VISION] model={model}")
    vision_log(f"[VISION] input_image_count={len(urls)}")
    if not cfg["api_url"] or not cfg["api_key"] or not cfg["model"]:
        vision_log("[VISION][config_missing] skip remote vision call and downgrade gracefully")
        return VISION_USER_FALLBACK

    result = analyze_image_with_details(local_path, user_text=user_text, input_image_urls=urls)
    vision_log(f"[VISION] request_url={result.request_url}")
    vision_log(f"[VISION] model={result.model}")
    vision_log(f"[VISION] input_image_count={result.input_image_count}")
    vision_log(f"[VISION] input_image_urls={result.input_image_urls}")
    vision_log(f"[VISION] http_status={result.http_status}")
    vision_log(f"[VISION] response_preview={result.response_preview!r}")
    if result.error:
        vision_log(f"[VISION] error={result.error}")
    if result.traceback:
        vision_log(f"[VISION][traceback] {result.traceback}")

    if result.status == "ok":
        vision_log("[VISION] api success")
        return result.content

    if result.status == "response_parse_failed":
        vision_log("[VISION][response_parse_failed] unable to parse response payload")
        return "我看到了图片，但暂时没识别出明确内容。"

    vision_log(f"[VISION][{result.status}] vision call failed and downgraded")
    return VISION_USER_FALLBACK


def _mask_request_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _detect_placeholder_values(cfg: dict) -> list[str]:
    placeholder_map = {
        "VISION_API_URL": {
            "https://your-vision-endpoint.example.com/v1/chat/completions",
            "your_vision_endpoint_here",
        },
        "VISION_API_KEY": {
            "your_api_key_here",
            "your_vision_api_key_here",
        },
        "VISION_MODEL": {
            "your_vision_model_here",
            "your_model_here",
        },
    }
    hits = []
    env_to_cfg_key = {
        "VISION_API_URL": "api_url",
        "VISION_API_KEY": "api_key",
        "VISION_MODEL": "model",
    }
    for env_name, cfg_key in env_to_cfg_key.items():
        value = str(cfg.get(cfg_key, "")).strip()
        if value in placeholder_map[env_name]:
            hits.append(env_name)
    return hits
