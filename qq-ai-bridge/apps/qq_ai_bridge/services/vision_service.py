"""Vision pipeline service for QQ bridge."""

import traceback
from typing import Iterable

from apps.qq_ai_bridge.config.settings import IMAGE_TMP_DIR
from image_utils import download_image
from vision.client import analyze_image_with_details, read_vision_config

VISION_USER_FALLBACK = "我这边暂时看不了图，稍后再试试。"
VISION_USER_DOWNLOAD_FALLBACK = "这张图我暂时没拿到，麻烦稍后重发试试。"


def log_vision_config_status(log=print) -> None:
    cfg = read_vision_config()
    has_url = bool(cfg["api_url"])
    has_key = bool(cfg["api_key"])
    has_model = bool(cfg["model"])
    log(f"[VISION][CONFIG] VISION_API_URL detected={has_url}")
    log(f"[VISION][CONFIG] VISION_API_KEY detected={has_key}")
    log(f"[VISION][CONFIG] VISION_MODEL detected={has_model}")
    if not (has_url and has_key and has_model):
        log("[VISION][CONFIG] missing required vision config, image understanding will degrade gracefully")


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
