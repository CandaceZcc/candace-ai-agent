import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.reply_models import ImageSocialClassification
from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.skills.image_understanding import ImageUnderstandingSkill, _LAST_GROUP_VISION_REPLY_TS
from apps.qq_ai_bridge.skills.image_understanding import _sanitize_group_vision_reply


class ImageUnderstandingTests(unittest.TestCase):
    def setUp(self):
        _LAST_GROUP_VISION_REPLY_TS.clear()

    def test_sanitize_sensitive_reply(self):
        self.assertEqual(
            _sanitize_group_vision_reply("哈哈，这表情包太逗了，鸡巴很香", has_text=False, force_reply=False),
            "这图有点抽象。",
        )

    def test_sanitize_drops_generic_cute_reply_for_passive_image(self):
        self.assertEqual(
            _sanitize_group_vision_reply("哈哈，这表情太可爱了", has_text=False, force_reply=False),
            "",
        )

    def test_sanitize_keeps_reply_when_force_reply(self):
        self.assertEqual(
            _sanitize_group_vision_reply("哈哈，这表情太可爱了", has_text=False, force_reply=True),
            "哈哈，这表情太可爱了",
        )

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.send_group_msg")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("meme", "joke", "short_text", 0.88, "showoff", short_text="有梗。"),
    )
    def test_group_image_uses_reply_all_messages_trigger(self, _mock_social, mock_send_group_msg, _mock_append_log):
        skill = ImageUnderstandingSkill()
        context = SkillContext(
            data={"message_id": 5566},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=None,
            group_id=810938203,
            group_config={"bot_can_reply": True, "enable_vision": True, "reply_all_messages": True},
            should_log=True,
            msg="",
            normalized_msg="",
            effective_text="",
            mentioned_self=False,
            image_inputs={"has_image": True, "image_urls": ["https://example.com/a.jpg"], "text": ""},
            file_info=None,
            logger=lambda *_args, **_kwargs: None,
            timestamp=1,
            message_id=5566,
            nick="tester",
            raw_message="",
        )

        result = skill.handle(context)

        self.assertTrue(result.handled)
        mock_send_group_msg.assert_called_once()
        self.assertEqual(mock_send_group_msg.call_args.kwargs["reply_to_message_id"], 5566)
        logged_payload = _mock_append_log.call_args.args[2]
        self.assertEqual(logged_payload["image_type"], "meme")
        self.assertEqual(logged_payload["social_intent"], "joke")

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.react_message_with_preferred_emojis", return_value={"ok": True, "emoji_name": "laugh_cry"})
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("meme", "joke", "reaction", 0.9, "meme", short_text="有梗。", emoji_name="laugh_cry"),
    )
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline")
    def test_group_image_reaction_path_skips_vision(
        self,
        mock_vision,
        _mock_social,
        mock_react,
        _mock_append_log,
    ):
        skill = ImageUnderstandingSkill()
        context = SkillContext(
            data={"message_id": 7788},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=None,
            group_id=810938203,
            group_config={"bot_can_reply": True, "enable_vision": True, "reply_all_messages": True},
            should_log=True,
            msg="",
            normalized_msg="",
            effective_text="",
            mentioned_self=False,
            image_inputs={"has_image": True, "image_urls": ["https://example.com/a.jpg"], "text": ""},
            file_info=None,
            logger=lambda *_args, **_kwargs: None,
            timestamp=1,
            message_id=7788,
            nick="tester",
            raw_message="",
        )

        result = skill.handle(context)

        self.assertTrue(result.handled)
        mock_react.assert_called_once()
        mock_vision.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.send_group_msg")
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="这是一张截图，写着错误信息。")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("screenshot", "ask_identify", "full_text", 0.95, "identify_request", short_text="我先帮你看下。"),
    )
    def test_group_image_full_text_path_uses_vision(
        self,
        _mock_social,
        mock_vision,
        mock_send_group_msg,
        _mock_append_log,
    ):
        skill = ImageUnderstandingSkill()
        context = SkillContext(
            data={"message_id": 8899},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=None,
            group_id=810938203,
            group_config={"bot_can_reply": True, "enable_vision": True, "reply_all_messages": True},
            should_log=True,
            msg="这图写了啥",
            normalized_msg="这图写了啥",
            effective_text="这图写了啥",
            mentioned_self=False,
            image_inputs={"has_image": True, "image_urls": ["https://example.com/a.jpg"], "text": "这图写了啥"},
            file_info=None,
            logger=lambda *_args, **_kwargs: None,
            timestamp=1,
            message_id=8899,
            nick="tester",
            raw_message="",
        )

        result = skill.handle(context)

        self.assertTrue(result.handled)
        mock_vision.assert_called_once()
        mock_send_group_msg.assert_called_once()
        logged_payload = _mock_append_log.call_args.args[2]
        self.assertEqual(logged_payload["image_type"], "screenshot")
        self.assertEqual(logged_payload["social_intent"], "ask_identify")
        self.assertEqual(logged_payload["source"], "image_understanding:full_text")


if __name__ == "__main__":
    unittest.main()
