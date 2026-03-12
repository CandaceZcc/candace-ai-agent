"""Vision pipeline service for QQ bridge."""

from apps.qq_ai_bridge.config.settings import IMAGE_TMP_DIR
from image_utils import download_image
from vision.client import analyze_image

VISION_CONFIG_FALLBACK = "识图服务暂不可用，请检查 VISION_API_URL / VISION_API_KEY / VISION_MODEL 配置。"
VISION_RUNTIME_FALLBACK = "识图服务调用失败，请稍后重试。"


def run_vision_pipeline(image_url: str, user_text: str, vision_log, save_dir=IMAGE_TMP_DIR) -> str:
    """Download an image, call the vision client, and return a short reply."""
    if not image_url:
        vision_log("[VISION] error: missing image_url")
        return "没有拿到图片链接，请重试发送图片。"

    vision_log(f"[VISION] vision service called image_url={image_url}")

    try:
        local_path = download_image(image_url, save_dir=save_dir)
        vision_log(f"[VISION] download success: {local_path}")
    except Exception as e:
        vision_log(f"[VISION] error: download failed: {e}")
        return "图片下载失败了"

    reply = analyze_image(local_path, user_text=user_text)
    if reply == "识图功能还没配置好":
        vision_log("[VISION] error: vision api not configured")
        return VISION_CONFIG_FALLBACK
    if reply == "看图的时候出了点问题":
        vision_log("[VISION] error: vision api call failed")
        return VISION_RUNTIME_FALLBACK
    if reply == "我看了图，但暂时没整理出结果":
        vision_log("[VISION] api success but empty result")
        return "我看到了图片，但暂时没识别出明确内容。"

    vision_log("[VISION] api success")
    return reply
