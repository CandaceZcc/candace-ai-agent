"""Skill for image understanding requests."""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from storage_utils import append_private_history, append_private_style_sample
from storage_utils import append_group_chat_log

from shared.ai.llm_client import call_ai

from apps.qq_ai_bridge.adapters.napcat_client import react_message_with_multiple_emojis, send_group_msg, send_private_msg
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR, GLOBAL_LISTEN_GROUP_IDS, VISION_GROUP_COOLDOWN_SECONDS
from apps.qq_ai_bridge.services.emoji_service import infer_reaction_preferred_order
from apps.qq_ai_bridge.services.image_social_service import classify_group_image_social, rewrite_group_vision_reply
from apps.qq_ai_bridge.services.private_chat_service import get_user_workspace
from apps.qq_ai_bridge.services.prompt_service import build_vision_user_text
from apps.qq_ai_bridge.services.vision_service import run_vision_pipeline
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult

_LAST_GROUP_VISION_REPLY_TS: dict[str, int] = {}
_LAST_GROUP_VISION_READ_TS: dict[str, int] = {}
VISION_GROUP_PASSIVE_READ_INTERVAL_SECONDS = 0
_VISION_GENERIC_CUTE_PATTERN = re.compile(r"(哈哈|哇|好可爱|太可爱|萌翻|想rua|笑死我了)")
_VISION_EMOJI_STICKER_PATTERN = re.compile(r"(表情包|贴纸|emoji|Q版|梗图|斗图|猫猫头|狗头|黄豆|meme)", re.IGNORECASE)


@dataclass
class VisionGroupDecision:
    action: str
    emoji_name: str = ""
    reply: str = ""
    reason: str = ""


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

        if (
            social.suggested_action != "reaction"
            and not context.mentioned_self
            and not keyword_triggered
            and _is_group_vision_cooldown(context.group_id)
        ):
            context.log("[VISION] skipped by cooldown")
            return SkillResult(handled=True, source=self.name, status="ignore")

        if social.suggested_action == "reaction":
            vision_decision = VisionGroupDecision("reaction", emoji_name=social.emoji_name, reason="social_default")
            vision_reply = ""
            if _should_read_passive_group_image(context.group_id, bool(vision_text), bool(context.mentioned_self or keyword_triggered)):
                context.log("[VISION] passive reaction reads image for decision")
                vision_reply = run_vision_pipeline(image_urls, vision_text, vision_log)
                vision_decision = _decide_group_image_action_from_vision_reply(
                    vision_reply,
                    has_user_text=bool(vision_text),
                    force_reply=bool(context.mentioned_self or keyword_triggered),
                    social=social,
                )
                _LAST_GROUP_VISION_READ_TS[str(context.group_id or "")] = int(time.time())
                context.log(
                    "[VISION] passive image decision "
                    f"action={vision_decision.action} emoji={vision_decision.emoji_name or '-'} "
                    f"reason={vision_decision.reason} preview={vision_reply[:80]!r}"
                )
            if vision_decision.action == "no_reply":
                _append_group_image_context_log(context, social, vision_text, vision_reply, source_action="no_reply")
                context.log(f"[VISION] image decision chose no_reply reason={vision_decision.reason}")
                return SkillResult(handled=True, source=self.name, status="ignore")
            if vision_decision.action == "text":
                reply = vision_decision.reply or social.short_text or "这图有点东西。"
                reply = _generate_group_image_critique_reply(vision_reply, social, vision_text, fallback=reply)
            elif target_message_id:
                preferred_order = (
                    (vision_decision.emoji_name,) if vision_decision.emoji_name else ()
                ) + (
                    (social.emoji_name,) if social.emoji_name else ()
                ) + infer_reaction_preferred_order(f"{vision_text}\n{social.reason}\n{vision_decision.reason}")
                deduped_order = tuple(dict.fromkeys(name for name in preferred_order if name))
                reaction_result = react_message_with_multiple_emojis(
                    target_message_id,
                    count=1,
                    quiet=not context.should_log,
                    preferred_order=deduped_order,
                    preserve_order=bool(vision_decision.emoji_name or social.emoji_name),
                )
                if reaction_result.get("ok"):
                    _append_group_image_context_log(
                        context,
                        social,
                        vision_text,
                        vision_reply,
                        source_action="reaction",
                        assistant=f"[reaction:{_first_reaction_name(reaction_result)}]",
                    )
                    context.log(
                        "[VISION] reply sent (group reaction) "
                        f"emoji={_first_reaction_name(reaction_result)} target={target_message_id}"
                    )
                    return SkillResult(handled=True, source=self.name, response_payload={"status": "ok", "source": "vision_reaction"})
            else:
                reply = vision_decision.reply or social.short_text or "这图有点东西。"
            if vision_decision.action == "reaction" and not social.short_text:
                _append_group_image_context_log(context, social, vision_text, vision_reply, source_action="reaction")
                context.log("[VISION] reaction path had no target and no short_text fallback")
                return SkillResult(handled=True, source=self.name, status="ignore")
        elif social.suggested_action == "short_text":
            reply = social.short_text or ""
        else:
            context.log("[VISION] vision service called (group)")
            vision_reply = run_vision_pipeline(image_urls, vision_text, vision_log)
            reply = _generate_group_image_critique_reply(
                vision_reply,
                social,
                vision_text,
                fallback=rewrite_group_vision_reply(vision_reply, social, vision_text),
            )
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


def _append_group_image_context_log(
    context: SkillContext,
    social,
    vision_text: str,
    vision_reply: str,
    *,
    source_action: str,
    assistant: str = "",
) -> None:
    summary = _compact_vision_text_reply(vision_reply) if vision_reply else ""
    append_group_chat_log(
        BASE_DATA_DIR,
        context.group_id,
        {
            "timestamp": int(context.timestamp or 0),
            "sender_name": context.nick or str(context.user_id or "?"),
            "user_id": context.user_id,
            "message": f"[图片] {vision_text}".strip(),
            "assistant": assistant or (f"[已读图] {summary}" if summary else "[已读图，未回复]"),
            "source": f"image_understanding:{source_action}",
            "image_type": social.image_type,
            "social_intent": social.social_intent,
            "image_reason": social.reason,
            "vision_summary": summary,
        },
        limit=500,
    )


def _should_read_passive_group_image(group_id, has_text: bool, force_reply: bool) -> bool:
    if VISION_GROUP_PASSIVE_READ_INTERVAL_SECONDS <= 0:
        return True
    if has_text or force_reply:
        return True
    key = str(group_id or "")
    if not key:
        return True
    last_ts = _LAST_GROUP_VISION_READ_TS.get(key, 0)
    return int(time.time()) - int(last_ts) >= VISION_GROUP_PASSIVE_READ_INTERVAL_SECONDS


def _decide_group_image_action_from_vision_reply(
    reply: str,
    has_user_text: bool,
    force_reply: bool,
    social=None,
) -> VisionGroupDecision:
    text = str(reply or "").strip()
    lowered = text.lower()
    confidence = float(getattr(social, "confidence", 0.0) or 0.0)
    image_type = str(getattr(social, "image_type", "") or "")
    if not text:
        return VisionGroupDecision("no_reply", reason="empty_vision_reply")
    if any(token in text for token in ("暂时看不了图", "暂时没拿到", "没识别出明确内容")):
        return VisionGroupDecision("no_reply", reason="vision_unavailable")
    if force_reply or has_user_text:
        return VisionGroupDecision("text", reply=_humanize_vision_text_reply(text), reason="requested_or_captioned")
    if any(token in text for token in ("报错", "错误", "截图", "代码", "作业", "聊天记录", "聊天截图", "对话", "群聊", "私聊", "二维码", "表格", "文档")):
        return VisionGroupDecision("text", reply=_humanize_vision_text_reply(text), reason="high_info_image")
    emoji_name = _infer_reaction_from_vision_reply(text)
    if emoji_name:
        return VisionGroupDecision("reaction", emoji_name=emoji_name, reason="vision_content_reaction")
    if any(token in text for token in ("我不太确定", "不确定", "看不清")):
        if confidence > 0.5:
            if image_type in {"meme", "anime", "low_info", "unknown"}:
                return VisionGroupDecision("reaction", emoji_name=getattr(social, "emoji_name", "") or "question", reason="uncertain_but_confident_low_info")
            return VisionGroupDecision("text", reply=_humanize_vision_text_reply(text), reason="uncertain_but_confident_value")
        return VisionGroupDecision("no_reply", reason="uncertain_low_info")
    if any(token in lowered for token in ("logo", "标志", "图标", "按钮", "背景", "海报", "封面")):
        return VisionGroupDecision("reaction", emoji_name="question", reason="generic_visual_object")
    return VisionGroupDecision("no_reply", reason="low_signal_image")


def _compact_vision_text_reply(reply: str) -> str:
    cleaned = re.sub(r"\s+", " ", str(reply or "")).strip()
    cleaned = re.sub(r"(?:^|\s)[0-9]+[)）]\s*", " ", cleaned)
    cleaned = re.sub(r"我不太确定。?$", "", cleaned).strip(" ，。！？,.!?:：；")
    if not cleaned:
        return "这图我看不太清。"
    if len(cleaned) > 34:
        return cleaned[:34].rstrip("，。！？,.!?:：； ") + "。"
    return cleaned


def _humanize_vision_text_reply(reply: str) -> str:
    text = _compact_vision_text_reply(reply)
    raw_text = str(reply or "")
    if any(token in text for token in ("点赞", "赞了", "关注", "转发", "收藏")):
        return _pick_social_ack_reply(text)
    if any(token in text for token in ("代码", "日志", "调试", "编辑器", "报错", "错误")):
        return "又在和日志打架了是吧。"
    if any(token in raw_text for token in ("聊天记录", "聊天截图", "对话", "群聊", "私聊")):
        return "这聊天记录有点东西。"
    if any(token in raw_text for token in ("手机截图", "屏幕截图", "截图", "群成员", "用户发送", "消息")):
        return _pick_screenshot_comment(raw_text)
    if any(token in text for token in ("二维码", "表格", "文档")):
        return "信息量有点大，得细看。"
    return _pick_generic_image_comment(raw_text or text)


def _generate_group_image_critique_reply(
    vision_reply: str,
    social,
    user_text: str = "",
    *,
    fallback: str = "",
) -> str:
    vision_text = str(vision_reply or "").strip()
    fallback_text = str(fallback or "").strip() or _humanize_vision_text_reply(vision_text)
    if not _should_generate_vision_critique(vision_text, social):
        return fallback_text
    prompt = (
        "你是QQ群友风格的图片短评生成器，只输出一句中文短评。\n"
        "目标：根据识图摘要评价图片，不要复述图片内容。\n"
        "风格：像群友接话，可幽默、轻吐槽、轻攻击性，但别做人身攻击，别解释。\n"
        "硬规则：\n"
        "1) 8到22字，单句，不换行。\n"
        "2) 禁止使用：图片中、截图显示、看起来、这是一张、我不确定。\n"
        "3) 高信息/大量文字截图要评价其信息量、抽象程度、槽点或压迫感。\n"
        "4) 不要说你看不清，不要写分析步骤。\n"
        f"用户配文：{str(user_text or '').strip() or '无'}\n"
        f"识图摘要：{vision_text[:500]}"
    )
    try:
        raw = call_ai(
            prompt,
            metadata={
                "user_id": "vision_critique_selector",
                "prompt_mode": "group_image_critique",
                "query_len": len(vision_text),
            },
        )
    except Exception:
        return fallback_text
    cleaned = _sanitize_vision_critique_reply(raw)
    if not cleaned:
        return fallback_text
    return cleaned


def _should_generate_vision_critique(vision_reply: str, social) -> bool:
    text = str(vision_reply or "")
    if not text or text == "视觉服务暂不可用。":
        return False
    lowered = text.lower()
    if any(token in lowered for token in ("表情包", "贴纸", "emoji", "q版", "meme")):
        return False
    if any(token in text for token in ("截图", "聊天记录", "聊天群", "群成员", "代码", "日志", "报错", "错误", "文字", "文本", "网址", "JSON")):
        return True
    image_type = str(getattr(social, "image_type", "") or "")
    return image_type in {"screenshot", "chat_record", "document", "product"}


def _sanitize_vision_critique_reply(reply: str) -> str:
    text = str(reply or "").strip()
    if not text:
        return ""
    text = re.sub(r"```.*?```", "", text, flags=re.S).strip()
    text = re.sub(r"^[\s\"'“”]+|[\s\"'“”]+$", "", text)
    text = " ".join(text.splitlines()).strip()
    text = re.sub(r"^(短评|评价|回复|输出)[:：]\s*", "", text).strip()
    banned = ("图片中", "截图显示", "看起来", "这是一张", "我不确定", "屏幕上显示", "显示的是")
    if any(token in text for token in banned):
        return ""
    if len(text) > 28:
        text = text[:28].rstrip("，。！？,.!?:：； ") + "。"
    if len(text) < 2:
        return ""
    return text


def _pick_screenshot_comment(text: str) -> str:
    candidates = (
        "这截图味儿挺冲。",
        "这群名一看就不太正常。",
        "信息量挺大，已经开始抽象了。",
        "这场面有点赛博围观。",
    )
    return candidates[abs(hash(text)) % len(candidates)]


def _pick_generic_image_comment(text: str) -> str:
    candidates = (
        "有点东西。",
        "这张挺抽象。",
        "味儿对了。",
        "这图攻击性还行。",
    )
    return candidates[abs(hash(text)) % len(candidates)]


def _pick_social_ack_reply(text: str) -> str:
    candidates = (
        "爸爸",
        "妈妈",
        "可以",
        "设了",
    )
    return candidates[abs(hash(text)) % len(candidates)]


def _infer_reaction_from_vision_reply(reply: str) -> str:
    text = str(reply or "").lower()
    if not text:
        return ""
    if any(token in text for token in ("猫", "狗", "可爱", "萌", "宠物", "动物", "二次元", "动漫")):
        return "lollipop"
    if any(token in text for token in ("笑", "搞笑", "梗", "表情包", "meme", "抽象", "离谱", "绷")):
        return "laugh_cry"
    if any(token in text for token in ("色情", "涩图", "性感", "舔屏", "擦边", "腿", "短裤", "胸", "屁股", "身材", "裸", "泳装", "吊带", "黑丝", "白丝")):
        return "lick_screen"
    if any(token in text for token in ("问题", "报错", "截图", "看不清", "不确定", "文字", "代码")):
        return "question"
    return ""


def _first_reaction_name(reaction_result: dict) -> str:
    names = reaction_result.get("emoji_names") or []
    if names:
        return str(names[0])
    return str(reaction_result.get("emoji_name") or "")


def _sanitize_group_vision_reply(reply: str, has_text: bool, force_reply: bool) -> str:
    cleaned = str(reply or "").strip()
    if not cleaned:
        return ""
    cleaned = re.sub(r"(?:^|\s)\d+\)\s*", " ", cleaned)
    cleaned = " ".join(cleaned.splitlines()).strip()
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
