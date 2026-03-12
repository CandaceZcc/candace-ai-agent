"""Skill for image understanding requests."""

from __future__ import annotations

from apps.qq_ai_bridge.adapters.napcat_client import send_group_msg, send_private_msg
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR
from apps.qq_ai_bridge.services.private_chat_service import get_user_workspace
from apps.qq_ai_bridge.services.prompt_service import build_vision_user_text
from apps.qq_ai_bridge.services.vision_service import run_vision_pipeline
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult
from storage_utils import append_private_history, append_private_style_sample


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

        reply_all_messages = context.group_config.get("reply_all_messages", False)
        keyword_triggered = context.image_inputs.get("text", "").startswith("ai ")
        if not (context.mentioned_self or reply_all_messages or keyword_triggered):
            context.log("[VISION] image present but group trigger not met")
            return SkillResult(handled=False, source=self.name, status="ignore")

        context.log("[VISION] vision service called (group)")
        reply = run_vision_pipeline(image_urls, vision_text, vision_log)
        payload = {"status": "ok", "source": "vision"}
        context.log(f"[VISION] response payload built: {payload}")
        send_group_msg(context.group_id, reply, quiet=not context.should_log)
        context.log("[VISION] reply sent (group)")
        return SkillResult(handled=True, source=self.name, response_payload=payload)
