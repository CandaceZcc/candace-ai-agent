"""QQ `/draw` image-generation skill."""

from __future__ import annotations

from apps.qq_ai_bridge.adapters.napcat_client import (
    send_group_image,
    send_group_msg,
    send_private_image,
    send_private_msg,
)
from apps.qq_ai_bridge.services.draw_service import DrawResult, generate_image
from apps.qq_ai_bridge.services.runtime_resources import submit_media_task
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult
from apps.qq_ai_bridge.logging.bridge_log import log_warn

_DRAW_COMMAND = "/draw"
_DRAW_USAGE = "用法：/draw 你想画的内容"
_DRAW_QUEUED = "正在画，稍等一下。"


def _extract_draw_prompt(text: str) -> str:
    normalized = str(text or "")
    command_index = normalized.find(_DRAW_COMMAND)
    if command_index < 0:
        return ""
    return normalized[command_index + len(_DRAW_COMMAND):].strip()


class DrawSkill:
    """Handle asynchronous image-generation commands."""

    name = "draw"

    def match_reason(self, context: SkillContext) -> str:
        return "draw_command" if _DRAW_COMMAND in context.effective_text else "no_draw_command"

    def can_handle(self, context: SkillContext) -> bool:
        return _DRAW_COMMAND in str(context.effective_text or "")

    def handle(self, context: SkillContext) -> SkillResult:
        if context.is_group and not context.group_config.get("bot_can_reply", True):
            return SkillResult(handled=True, source=self.name, status="ignore")

        prompt = _extract_draw_prompt(context.effective_text)
        if not prompt:
            _send_text(context, _DRAW_USAGE)
            return SkillResult(handled=True, source=self.name, status="invalid_prompt")

        reference_urls = context.image_inputs.get("image_urls") or []
        reference_image_url = str(reference_urls[0] or "") if reference_urls else ""
        future = submit_media_task(_run_draw_worker, context, prompt, reference_image_url)
        if future is None:
            _send_text(context, "当前画图任务较多，请稍后再试。")
            return SkillResult(handled=True, source=self.name, status="busy")
        _send_text(context, _DRAW_QUEUED)
        return SkillResult(
            handled=True,
            source=self.name,
            status="queued",
            response_payload={"status": "queued"},
        )


def _run_draw_worker(
    context: SkillContext,
    prompt: str,
    reference_image_url: str,
) -> None:
    try:
        result = generate_image(prompt, reference_image_url=reference_image_url)
    except Exception as exc:
        log_warn("DRAW", "worker failed error_type=%s", type(exc).__name__)
        _send_text(context, "画图失败了，稍后再试。", quiet=True)
        return
    if result.status == "completed" and result.image_url:
        send_result = _send_image(context, result.image_url)
        if not send_result.get("ok"):
            _send_text(context, result.image_url, quiet=True)
        return
    _send_text(context, _draw_error_message(result), quiet=True)


def _send_image(context: SkillContext, image_url: str) -> dict:
    if context.is_group:
        return send_group_image(
            context.group_id,
            image_url,
            quiet=True,
            reply_to_message_id=context.message_id,
        )
    return send_private_image(context.user_id, image_url, quiet=True)


def _send_text(context: SkillContext, text: str, *, quiet: bool = False) -> dict:
    if context.is_group:
        return send_group_msg(
            context.group_id,
            text,
            quiet=quiet,
            reply_to_message_id=context.message_id,
        )
    return send_private_msg(context.user_id, text, quiet=quiet) if quiet else send_private_msg(
        context.user_id,
        text,
    )


def _draw_error_message(result: DrawResult) -> str:
    if result.status == "timeout":
        return "画图超时了，稍后再试。"
    if result.status == "config_missing":
        return "画图功能还没配置好。"
    if result.status == "reference_image_failed":
        return "参考图读取失败，请重新发送。"
    return "画图失败了，稍后再试。"
