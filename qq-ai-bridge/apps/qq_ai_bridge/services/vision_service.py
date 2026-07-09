"""Vision pipeline service for QQ bridge."""

import re
from typing import Iterable
from urllib.parse import urlparse

from image_utils import download_image
from vision.client import analyze_image_with_details, read_vision_config

from apps.qq_ai_bridge.config.settings import IMAGE_TMP_DIR

VISION_USER_FALLBACK = "我这边暂时看不了图，稍后再试试。"
VISION_USER_DOWNLOAD_FALLBACK = "这张图我暂时没拿到，麻烦稍后重发试试。"


# log_vision_config_status：打印视觉配置状态
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
    legacy_models = _detect_legacy_vision_model_values(cfg)
    for model in legacy_models:
        log(
            "[VISION][CONFIG][WARNING] legacy vision model "
            f"{model!r} detected; recommended Moonshot multimodal model is 'kimi-k2.6'"
        )


# run_vision_pipeline：调用视觉模型识图
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
        local_path = _download_image_with_retry(first_url, save_dir=save_dir, vision_log=vision_log)
        vision_log(f"[VISION] download success: {local_path}")
    except Exception as exc:
        vision_log(
            "[VISION][image_url_unreachable] download failed "
            f"url={first_url} error_type={type(exc).__name__} error={_compact_error(exc)}"
        )
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
        return _postprocess_vision_reply(result.content, user_text=user_text)

    if result.status == "response_parse_failed":
        vision_log("[VISION][response_parse_failed] unable to parse response payload")
        return "我看到了图片，但暂时没识别出明确内容。"

    vision_log(f"[VISION][{result.status}] vision call failed and downgraded")
    return VISION_USER_FALLBACK


def _download_image_with_retry(url: str, save_dir: str, vision_log, attempts: int = 2) -> str:
    last_error: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return download_image(url, save_dir=save_dir)
        except Exception as exc:
            last_error = exc
            if attempt < attempts:
                vision_log(
                    "[VISION][image_download_retry] "
                    f"attempt={attempt} error_type={type(exc).__name__} error={_compact_error(exc)}"
                )
    if last_error:
        raise last_error
    raise RuntimeError("download failed")


def _compact_error(exc: Exception) -> str:
    text = " ".join(str(exc or "").split())
    if len(text) > 180:
        return text[:180].rstrip() + "..."
    return text


# _postprocess_vision_reply：视觉回复处理
def _postprocess_vision_reply(reply: str, user_text: str = "") -> str:
    raw = str(reply or "").strip()
    if not raw:
        return "我看到了图，但我不太确定。"

    # 优先解析模型三段式，避免把 `2)` 这种编号带进最终回复。
    segments = re.findall(r"(?:^|\n)\s*(\d+)\)\s*(.+?)(?=(?:\n\s*\d+\))|$)", raw, flags=re.DOTALL)
    parts = {}
    for index, content in segments:
        parts[index] = " ".join(content.split()).strip("，。！？,.!?:：； ")

    objective = parts.get("1", "")
    vibe = parts.get("2", "")
    uncertain = parts.get("3", "")

    if not objective:
        normalized = " ".join(raw.splitlines()).strip()
        normalized = re.sub(r"(?:^|\s)\d+\)\s*", " ", normalized)
        objective = " ".join(normalized.split()).strip("，。！？,.!?:：； ")

    objective = objective.replace("这是一张", "这图是").replace("这是一只", "图里是只")
    objective = objective.replace("卡通", "Q版").replace("玩偶", "摆件")
    objective = objective.replace("哈哈", "").replace("太可爱了", "").replace("萌翻", "")
    objective = " ".join(objective.split()).strip("，。！？,.!?:：； ")

    if not objective:
        objective = "我看到了图。"

    if len(objective) > 24:
        objective = objective[:24].rstrip("，。！？,.!?:：； ") + "。"

    text = objective
    if vibe and len(vibe) <= 12:
        cleaned_vibe = vibe.replace("哈哈", "").replace("太可爱了", "挺可爱")
        cleaned_vibe = cleaned_vibe.strip("，。！？,.!?:：； ")
        if cleaned_vibe:
            text = f"{text} {cleaned_vibe}"

    asks_detail = any(token in str(user_text or "") for token in ("?", "？", "看清", "写了啥", "是什么", "啥意思", "怎么"))
    if "不确定" in uncertain and "不太确定" not in text:
        text = f"{text} 我不太确定。"
    elif asks_detail and "不确定" not in text:
        text = f"{text} 我不太确定。"

    return " ".join(text.split())


# _mask_request_url：遮蔽URL
def _mask_request_url(url: str) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        return url
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


# _detect_placeholder_values：检测占位值
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


def _detect_legacy_vision_model_values(cfg: dict) -> list[str]:
    legacy_models = {
        "moonshot-v1-32k-vision-preview",
        "moonshot-v1-8k-vision-preview",
        "moonshot-v1-128k-vision-preview",
    }
    model = str(cfg.get("model", "")).strip()
    return [model] if model in legacy_models else []
