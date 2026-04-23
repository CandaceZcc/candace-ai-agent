"""Skill for image understanding requests."""

from __future__ import annotations

import re
import time

from storage_utils import append_private_history, append_private_style_sample
from storage_utils import append_group_chat_log

from apps.qq_ai_bridge.adapters.napcat_client import react_message_with_preferred_emojis, send_group_msg, send_private_msg
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR, GLOBAL_LISTEN_GROUP_IDS, VISION_GROUP_COOLDOWN_SECONDS
from apps.qq_ai_bridge.services.image_social_service import classify_group_image_social, rewrite_group_vision_reply
from apps.qq_ai_bridge.services.private_chat_service import get_user_workspace
from apps.qq_ai_bridge.services.prompt_service import build_vision_user_text
from apps.qq_ai_bridge.services.vision_service import run_vision_pipeline
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult

_LAST_GROUP_VISION_REPLY_TS: dict[str, int] = {}
_VISION_SENSITIVE_PATTERN = re.compile(r"鸡巴|跳蛋|想妈妈了|性|骚|做爱|操", re.IGNORECASE)
_VISION_GENERIC_CUTE_PATTERN = re.compile(r"(哈哈|哇|好可爱|太可爱|萌翻|想rua|笑死我了)")
_VISION_EMOJI_STICKER_PATTERN = re.compile(r"(表情包|贴纸|emoji|Q版|梗图|斗图|猫猫头|狗头|黄豆|meme)", re.IGNORECASE)


class ImageUnderstandingSkill:
    """Handle image messages in private and group chats."""

    name = "image_understanding"

    def match_reason(self, context: SkillContext) -> str:
        """Return human-readable match reason for debug logs."""
        if not context.image_inputs.get("has_image"):
            return "no_image"
        return "image_present"

    def can_handle(self, context: SkillContext) -> bool:
        """Only handle messages that contain images."""
        return bool(context.image_inputs.get("has_image"))

    def handle(self, context: SkillContext) -> SkillResult:
        """Run the vision pipeline if current context allows it."""
        context.log("[VISION] image_understanding selected")
        context.log("[VISION] image URLs extracted: %s" % (context.image_inputs.get("image_urls", []),))
        if context.image_inputs.get("resolved_relative_urls"):
            context.log("[VISION] resolved relative image URLs: %s" % (context.image_inputs.get("resolved_relative_urls", []),))
        if context.image_inputs.get("dropped_image_urls"):
            context.log("[VISION] dropped non-absolute image URLs: %s" % (context.image_inputs.get("dropped_image_urls", []),))

        vision_text = build_vision_user_text(context.image_inputs.get("text", ""))
        image_urls = context.image_inputs.get("image_urls", [])

        def vision_log(message: str) -> None:
            context.log(message)

        if context.is_private:
            get_user_workspace(context.user_id)
            if vision_text:
                append_private_style_sample(BASE_DATA_DIR, context.user_id, vision_text, timestamp=context.timestamp)

            context.log("[VISION] vision service called (private)")
            reply = run_vision_pipeline(image_urls, vision_text, vision_log)
            append_private_history(BASE_DATA_DIR, context.user_id, f"[image] {vision_text}".strip(), reply, limit=20)

            payload = {"status": "ok", "source": "vision"}
            context.log(f"[VISION] response payload built: {payload}")
            send_private_msg(context.user_id, reply)
            context.log("[VISION] reply sent (private)")
            return SkillResult(handled=True, source=self.name, response_payload=payload)

        if not context.group_config.get("bot_can_reply", True):
            context.log("[VISION] skipped by config")
            return SkillResult(handled=True, source=self.name, status="ignore")
        if context.group_config.get("enable_vision") is False:
            context.log("[VISION] skipped by config")
            return SkillResult(handled=False, source=self.name, status="ignore")

        global_listen = (
            bool(context.group_config.get("reply_all_messages", False))
            or int(context.group_id or 0) in GLOBAL_LISTEN_GROUP_IDS
        )
        keyword_triggered = context.image_inputs.get("text", "").startswith("ai ")
        if global_listen:
            trigger_ok = bool(context.mentioned_self or keyword_triggered or context.group_config.get("reply_all_messages", False))
            if not trigger_ok:
                trigger_ok = not vision_text
            if not trigger_ok:
                context.log("[VISION] image present but global-listen trigger not met")
                return SkillResult(handled=False, source=self.name, status="ignore")
        else:
            trigger_ok = bool(context.mentioned_self or keyword_triggered)
            if not trigger_ok:
                context.log("[VISION] image present but mention trigger not met")
                return SkillResult(handled=False, source=self.name, status="ignore")

        if not context.mentioned_self and not keyword_triggered and _is_group_vision_cooldown(context.group_id):
            context.log("[VISION] skipped by cooldown")
            return SkillResult(handled=True, source=self.name, status="ignore")

        if not (context.mentioned_self or keyword_triggered or global_listen):
            context.log("[VISION] image present but group trigger not met")
            return SkillResult(handled=False, source=self.name, status="ignore")

        social = classify_group_image_social(image_urls, vision_text, vision_log)
        context.log(
            "[VISION] social classification: "
            f"image_type={social.image_type} intent={social.social_intent} "
            f"action={social.suggested_action} confidence={social.confidence} reason={social.reason}"
        )

        target_message_id = context.message_id or context.data.get("message_id")

        if social.suggested_action == "no_reply":
            context.log("[VISION] social classifier chose no_reply")
            return SkillResult(handled=True, source=self.name, status="ignore")

        if social.suggested_action == "reaction":
            if target_message_id:
                preferred_order = (
                    (social.emoji_name,) if social.emoji_name else ()
                ) + ("laugh_cry", "red_button", "lollipop", "lick_screen")
                deduped_order = tuple(dict.fromkeys(name for name in preferred_order if name))
                reaction_result = react_message_with_preferred_emojis(
                    target_message_id,
                    quiet=not context.should_log,
                    preferred_order=deduped_order,
                )
                if reaction_result.get("ok"):
                    context.log(
                        "[VISION] reply sent (group reaction) "
                        f"emoji={reaction_result.get('emoji_name')} target={target_message_id}"
                    )
                    _LAST_GROUP_VISION_REPLY_TS[str(context.group_id)] = int(time.time())
                    return SkillResult(handled=True, source=self.name, response_payload={"status": "ok", "source": "vision_reaction"})
            if not social.short_text:
                context.log("[VISION] reaction path had no target and no short_text fallback")
                return SkillResult(handled=True, source=self.name, status="ignore")
            reply = social.short_text
        elif social.suggested_action == "short_text":
            reply = social.short_text or ""
        else:
            context.log("[VISION] vision service called (group)")
            reply = run_vision_pipeline(image_urls, vision_text, vision_log)
            reply = rewrite_group_vision_reply(reply, social, vision_text)
            reply = _sanitize_group_vision_reply(
                reply,
                has_text=bool(vision_text),
                force_reply=bool(context.mentioned_self or keyword_triggered),
            )

        if not reply:
            context.log("[VISION] skipped by social strategy / sanitizer")
            return SkillResult(handled=True, source=self.name, status="ignore")
        payload = {"status": "ok", "source": "vision"}
        context.log(f"[VISION] response payload built: {payload}")
        append_group_chat_log(
            BASE_DATA_DIR,
            context.group_id,
            {
                "timestamp": int(context.timestamp or 0),
                "sender_name": context.nick or str(context.user_id or "?"),
                "user_id": context.user_id,
                "message": f"[图片] {vision_text}".strip(),
                "assistant": reply,
                "source": f"image_understanding:{social.suggested_action}",
                "image_type": social.image_type,
                "social_intent": social.social_intent,
                "image_reason": social.reason,
            },
            limit=500,
        )
        send_group_msg(
            context.group_id,
            reply,
            quiet=not context.should_log,
            reply_to_message_id=target_message_id,
        )
        _LAST_GROUP_VISION_REPLY_TS[str(context.group_id)] = int(time.time())
        context.log("[VISION] reply sent (group)")
        return SkillResult(handled=True, source=self.name, response_payload=payload)


def _is_group_vision_cooldown(group_id) -> bool:
    if VISION_GROUP_COOLDOWN_SECONDS <= 0:
        return False
    key = str(group_id or "")
    if not key:
        return False
    last_ts = _LAST_GROUP_VISION_REPLY_TS.get(key, 0)
    return int(time.time()) - int(last_ts) < VISION_GROUP_COOLDOWN_SECONDS


def _sanitize_group_vision_reply(reply: str, has_text: bool, force_reply: bool) -> str:
    cleaned = str(reply or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"(?:^|\s)\d+\)\s*", " ", cleaned)
    cleaned = " ".join(cleaned.splitlines()).strip()
    if _VISION_SENSITIVE_PATTERN.search(cleaned):
        return "这图有点抽象。"
    # 被动识图场景里，表情包/贴纸类图片默认沉默，避免机器人硬聊。
    if not has_text and not force_reply and _VISION_EMOJI_STICKER_PATTERN.search(cleaned):
        return ""
    if not has_text and not force_reply and _VISION_GENERIC_CUTE_PATTERN.search(cleaned):
        return ""
    if "我不确定" in cleaned:
        cleaned = re.sub(r"\s*我不确定.*$", " 我不太确定。", cleaned)
    if len(cleaned) > 36 and not force_reply:
        return cleaned[:36].rstrip("，。！？,.!?:：； ") + "。"
    return cleaned
