"""Two-phase social image classification for group chat."""

from __future__ import annotations

import re
from pathlib import Path

from image_utils import download_image

from apps.qq_ai_bridge.config.settings import IMAGE_TMP_DIR
from apps.qq_ai_bridge.services.meme_matcher import match_meme
from apps.qq_ai_bridge.services.reply_models import ImageSocialClassification

_IDENTIFY_TOKENS = ("是谁", "什么", "写了啥", "帮我看", "识别", "这啥", "看清")
_OPINION_TOKENS = ("好看吗", "怎么样", "评价", "咋样", "你们觉得")
_SHOWOFF_TOKENS = ("哈哈", "笑死", "绷不住", "绝了", "看看", "发个图", "这图")
_SCREENSHOT_TOKENS = ("报错", "截图", "界面", "弹窗", "聊天记录", "作业", "代码")
_ANIME_TOKENS = ("二次元", "老婆", "老公", "动漫", "番", "萌")
_PRODUCT_TOKENS = ("能买吗", "价格", "产品", "耳机", "手机", "电脑")
_LOW_INFO_TOKENS = ("表情包", "贴纸", "猫猫头", "狗头", "黄豆", "梗图", "meme", "斗图")


# classify_group_image_social：群聊图片社交处理
def classify_group_image_social(
    image_urls: list[str],
    user_text: str,
    vision_log=print,
) -> ImageSocialClassification:
    """Classify social intent before deciding whether vision is worth using."""
    normalized_text = str(user_text or "").strip()
    if not image_urls:
        return ImageSocialClassification("unknown", "unknown", "no_reply", 0.99, "missing_image")

    local_path = ""
    try:
        local_path = download_image(image_urls[0], save_dir=IMAGE_TMP_DIR)
        meme_result = match_meme(local_path)
        if meme_result.matched:
            return ImageSocialClassification(
                image_type="meme",
                social_intent="joke",
                suggested_action=meme_result.suggested_action,
                confidence=meme_result.confidence,
                reason=f"meme_match:{meme_result.tag}",
                short_text=meme_result.short_text or _build_human_short_reply("meme", "joke", normalized_text),
                emoji_name=meme_result.emoji_name,
            )
    except Exception as exc:
        vision_log(f"[VISION] meme matcher skipped error={exc}")
    finally:
        _try_remove(local_path)

    lowered = normalized_text.lower()
    if any(token in normalized_text for token in _IDENTIFY_TOKENS):
        return ImageSocialClassification(
            "screenshot",
            "ask_identify",
            "full_text",
            0.87,
            "identify_request",
            short_text="我先帮你看下。",
        )
    if any(token in normalized_text for token in _OPINION_TOKENS):
        return ImageSocialClassification(
            "real_photo",
            "ask_opinion",
            "short_text",
            0.78,
            "opinion_request",
            short_text=_build_human_short_reply("real_photo", "ask_opinion", normalized_text),
        )
    if any(token in normalized_text for token in _SCREENSHOT_TOKENS):
        return ImageSocialClassification(
            "screenshot",
            "evidence",
            "full_text",
            0.81,
            "screenshot_text",
            short_text="像是截图，我看看重点。",
        )
    if any(token in normalized_text for token in _PRODUCT_TOKENS):
        return ImageSocialClassification(
            "product",
            "ask_opinion",
            "short_text",
            0.72,
            "product_guess",
            short_text=_build_human_short_reply("product", "ask_opinion", normalized_text),
        )
    if any(token in normalized_text for token in _ANIME_TOKENS):
        return ImageSocialClassification(
            "anime",
            "showoff",
            "short_text",
            0.74,
            "anime_keyword",
            short_text=_build_human_short_reply("anime", "showoff", normalized_text),
            emoji_name="lollipop",
        )
    if any(token in lowered for token in _LOW_INFO_TOKENS):
        return ImageSocialClassification(
            "meme",
            "joke",
            "reaction",
            0.82,
            "low_info_sticker_text",
            short_text=_build_human_short_reply("meme", "joke", normalized_text),
            emoji_name="laugh_cry",
        )
    if any(token in lowered for token in _SHOWOFF_TOKENS):
        return ImageSocialClassification(
            "meme",
            "joke",
            "short_text",
            0.76,
            "showoff_text",
            short_text=_build_human_short_reply("meme", "joke", normalized_text),
            emoji_name="laugh_cry",
        )
    if not normalized_text:
        return ImageSocialClassification(
            "low_info",
            "showoff",
            "reaction",
            0.69,
            "image_only",
            short_text=_build_human_short_reply("low_info", "showoff", normalized_text),
            emoji_name="red_button",
        )
    return ImageSocialClassification(
        "unknown",
        "unknown",
        "short_text",
        0.42,
        "fallback_social_guess",
        short_text=_build_human_short_reply("unknown", "unknown", normalized_text),
    )


# rewrite_group_vision_reply：群聊视觉回复处理
def rewrite_group_vision_reply(reply: str, social: ImageSocialClassification, user_text: str) -> str:
    """Trim descriptive model outputs into something closer to group-chat speech."""
    cleaned = " ".join(str(reply or "").split()).strip()
    if not cleaned:
        return ""

    cleaned = re.sub(r"^(这是一[张个幅]|图中(?:显示|是|有)|这张图(?:里|中)?|图片(?:中|里)?)([^，。！？]*)[，。！？]?\s*", "", cleaned)
    cleaned = cleaned.strip()
    if social.social_intent == "ask_identify":
        return cleaned[:60].strip() or "我看不太清。"
    if social.image_type in {"meme", "anime", "low_info"} and "不确定" not in cleaned:
        cleaned = cleaned[:18].strip("，。！？,.!?:：； ")
    else:
        cleaned = cleaned[:32].strip("，。！？,.!?:：； ")
    if not cleaned:
        if social.suggested_action == "reaction":
            return ""
        return social.short_text or "有点东西。"
    return cleaned


# _build_human_short_reply：构建回复
def _build_human_short_reply(image_type: str, social_intent: str, user_text: str) -> str:
    lowered = str(user_text or "").lower()
    if social_intent == "ask_identify":
        return "我先认一下。"
    if social_intent == "ask_opinion":
        if image_type == "product":
            return "这得看你图啥。"
        return "这张还行。"
    if image_type == "anime":
        return "这张味儿挺足。"
    if image_type == "meme":
        if any(token in lowered for token in ("猫", "喵")):
            return "这张有点会。"
        return "有梗。"
    if image_type == "low_info":
        return "这图挺会挑。"
    return "有点东西。"


# _try_remove：相关逻辑处理
def _try_remove(path: str) -> None:
    if not path:
        return
    try:
        Path(path).unlink(missing_ok=True)
    except Exception:
        pass
