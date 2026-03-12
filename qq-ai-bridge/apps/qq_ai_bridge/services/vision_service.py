"""Vision pipeline service for QQ bridge."""

from apps.qq_ai_bridge.config.settings import IMAGE_TMP_DIR
from image_utils import download_image
from vision.client import analyze_image


def run_vision_pipeline(image_url: str, user_text: str, vision_log, save_dir=IMAGE_TMP_DIR) -> str:
    """Download an image, call the vision client, and return a short reply."""
    try:
        local_path = download_image(image_url, save_dir=save_dir)
        vision_log(f"[VISION] download success: {local_path}")
    except Exception as e:
        vision_log(f"[VISION] error: download failed: {e}")
        return "图片下载失败了"

    reply = analyze_image(local_path, user_text=user_text)
    if reply in {"识图功能还没配置好", "看图的时候出了点问题", "我看了图，但暂时没整理出结果"}:
        vision_log(f"[VISION] error: {reply}")
    else:
        vision_log("[VISION] api success")
    return reply
