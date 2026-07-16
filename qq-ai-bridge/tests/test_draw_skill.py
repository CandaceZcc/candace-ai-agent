import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.draw_service import DrawResult
from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.skills.draw import (
    DrawSkill,
    _extract_draw_prompt,
    _run_draw_worker,
)
from apps.qq_ai_bridge.skills.registry import build_skill_registry


def _context(
    text: str,
    *,
    message_type: str = "private",
    image_urls: list[str] | None = None,
) -> SkillContext:
    is_group = message_type == "group"
    return SkillContext(
        data={"message_id": 998877},
        post_type="message",
        message_type=message_type,
        user_id=67890,
        self_id=10000,
        group_id=12345 if is_group else None,
        group_config={"bot_can_reply": True},
        should_log=True,
        msg=text,
        normalized_msg=text,
        effective_text=text,
        mentioned_self=False,
        image_inputs={
            "has_image": bool(image_urls),
            "image_urls": image_urls or [],
            "text": text,
        },
        file_info=None,
        logger=lambda *_args, **_kwargs: None,
        timestamp=123,
        message_id=998877,
        nick="tester",
        raw_message=text,
    )


class DrawSkillTests(unittest.TestCase):
    def test_draw_skill_matches_draw_anywhere_in_message(self):
        skill = DrawSkill()

        self.assertTrue(skill.can_handle(_context("帮我 /draw 一只橘猫")))
        self.assertFalse(skill.can_handle(_context("帮我画一只橘猫")))

    def test_draw_skill_uses_text_after_first_draw_as_prompt(self):
        self.assertEqual(_extract_draw_prompt("前面的说明 /draw 未来城市雨夜"), "未来城市雨夜")

    @patch("apps.qq_ai_bridge.skills.draw.send_private_msg")
    def test_draw_skill_replies_with_usage_for_empty_prompt(self, mock_send):
        result = DrawSkill().handle(_context("/draw"))

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "invalid_prompt")
        mock_send.assert_called_once_with(67890, "用法：/draw 你想画的内容")

    @patch("apps.qq_ai_bridge.skills.draw.submit_media_task", return_value=object())
    @patch("apps.qq_ai_bridge.skills.draw.send_private_msg")
    def test_draw_skill_starts_worker_and_returns_handled(self, mock_send, mock_submit):
        result = DrawSkill().handle(
            _context(
                "/draw 把它改成杂志封面",
                image_urls=["https://example.com/reference.png"],
            )
        )

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "queued")
        mock_send.assert_called_once_with(67890, "正在画，稍等一下。")
        self.assertIs(mock_submit.call_args.args[0], _run_draw_worker)
        self.assertEqual(mock_submit.call_args.args[2], "把它改成杂志封面")
        self.assertEqual(
            mock_submit.call_args.args[3],
            "https://example.com/reference.png",
        )

    @patch("apps.qq_ai_bridge.skills.draw.submit_media_task", return_value=None)
    @patch("apps.qq_ai_bridge.skills.draw.send_private_msg")
    def test_draw_skill_reports_busy_without_claiming_task_was_queued(self, mock_send, _mock_submit):
        result = DrawSkill().handle(_context("/draw 一只猫"))

        self.assertEqual(result.status, "busy")
        mock_send.assert_called_once_with(67890, "当前画图任务较多，请稍后再试。")

    @patch("apps.qq_ai_bridge.skills.draw.send_private_image")
    @patch("apps.qq_ai_bridge.skills.draw.generate_image")
    def test_draw_worker_sends_private_image(self, mock_generate, mock_send_image):
        mock_generate.return_value = DrawResult(
            status="completed",
            image_url="https://cdn.example.com/result.png",
        )
        mock_send_image.return_value = {"ok": True}

        _run_draw_worker(_context("/draw 猫"), "猫", "")

        mock_generate.assert_called_once_with("猫", reference_image_url="")
        mock_send_image.assert_called_once_with(
            67890,
            "https://cdn.example.com/result.png",
            quiet=True,
        )

    @patch("apps.qq_ai_bridge.skills.draw.send_group_msg")
    @patch("apps.qq_ai_bridge.skills.draw.send_group_image")
    @patch("apps.qq_ai_bridge.skills.draw.generate_image")
    def test_draw_worker_falls_back_to_url_when_group_image_send_fails(
        self,
        mock_generate,
        mock_send_image,
        mock_send_text,
    ):
        mock_generate.return_value = DrawResult(
            status="completed",
            image_url="https://cdn.example.com/result.png",
        )
        mock_send_image.return_value = {"ok": False}

        _run_draw_worker(_context("/draw 猫", message_type="group"), "猫", "")

        mock_send_image.assert_called_once_with(
            12345,
            "https://cdn.example.com/result.png",
            quiet=True,
            reply_to_message_id=998877,
        )
        mock_send_text.assert_called_once_with(
            12345,
            "https://cdn.example.com/result.png",
            quiet=True,
            reply_to_message_id=998877,
        )

    @patch("apps.qq_ai_bridge.skills.draw.send_private_msg")
    @patch(
        "apps.qq_ai_bridge.skills.draw.generate_image",
        side_effect=RuntimeError("provider response crashed"),
    )
    def test_draw_worker_reports_unexpected_exception(self, _mock_generate, mock_send_text):
        _run_draw_worker(_context("/draw 猫"), "猫", "")

        mock_send_text.assert_called_once_with(
            67890,
            "画图失败了，稍后再试。",
            quiet=True,
        )

    def test_draw_skill_is_registered_before_image_understanding(self):
        names = [skill.name for skill in build_skill_registry()]

        self.assertLess(names.index("draw"), names.index("image_understanding"))


if __name__ == "__main__":
    unittest.main()
