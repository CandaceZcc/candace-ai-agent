import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.reply_models import ImageSocialClassification
from apps.qq_ai_bridge.skills.base import SkillContext
from apps.qq_ai_bridge.skills.image_understanding import ImageUnderstandingSkill, _LAST_GROUP_VISION_READ_TS, _LAST_GROUP_VISION_REPLY_TS
from apps.qq_ai_bridge.skills.image_understanding import _decide_group_image_action_from_vision_reply
from apps.qq_ai_bridge.skills.image_understanding import _generate_group_image_critique_reply, _sanitize_vision_critique_reply
from apps.qq_ai_bridge.skills.image_understanding import _humanize_vision_text_reply, _sanitize_group_vision_reply


class ImageUnderstandingTests(unittest.TestCase):
    def setUp(self):
        _LAST_GROUP_VISION_REPLY_TS.clear()
        _LAST_GROUP_VISION_READ_TS.clear()

    def _group_image_context(self, message_id=7788, text=""):
        return SkillContext(
            data={"message_id": message_id},
            post_type="message",
            message_type="group",
            user_id=1,
            self_id=None,
            group_id=810938203,
            group_config={"bot_can_reply": True, "enable_vision": True, "reply_all_messages": True},
            should_log=True,
            msg=text,
            normalized_msg=text,
            effective_text=text,
            mentioned_self=False,
            image_inputs={"has_image": True, "image_urls": ["https://example.com/a.jpg"], "text": text},
            file_info=None,
            logger=lambda *_args, **_kwargs: None,
            timestamp=1,
            message_id=message_id,
            nick="tester",
            raw_message="",
        )

    def test_sanitize_keeps_lowbrow_group_context(self):
        self.assertEqual(
            _sanitize_group_vision_reply("哈哈，这表情包太逗了，鸡巴很香", has_text=False, force_reply=True),
            "哈哈，这表情包太逗了，鸡巴很香",
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

    def test_humanize_vision_reply_for_like_notification(self):
        self.assertIn(
            _humanize_vision_text_reply("图片显示DJGenji点赞了视频。视频被点赞了，开心！我不太确定。"),
            {"爸爸", "妈妈", "可以", "设了"},
        )

    def test_humanize_vision_reply_comments_on_screenshot_without_describing(self):
        reply = _humanize_vision_text_reply(
            "这是一张手机截图，显示了一个名为“哈基米音乐作者群”的聊天群，群成员数量为194。看起来是个音乐创作群。我不太确定。"
        )

        self.assertIn(
            reply,
            {
                "这截图味儿挺冲。",
                "这群名一看就不太正常。",
                "信息量挺大，已经开始抽象了。",
                "这场面有点赛博围观。",
            },
        )
        self.assertNotIn("显示", reply)
        self.assertNotIn("音乐创作群", reply)

    @patch("apps.qq_ai_bridge.skills.image_understanding.call_ai", return_value="这群名攻击性很强。")
    def test_generate_group_image_critique_uses_llm_for_high_info(self, mock_call_ai):
        social = ImageSocialClassification("screenshot", "showoff", "text", 0.9, "screenshot")

        reply = _generate_group_image_critique_reply(
            "这是一张手机截图，显示了一个名为“哈基米音乐作者群”的聊天群，群成员数量为194。",
            social,
            fallback="这截图味儿挺冲。",
        )

        self.assertEqual(reply, "这群名攻击性很强。")
        mock_call_ai.assert_called_once()

    @patch("apps.qq_ai_bridge.skills.image_understanding.call_ai", return_value="图片中显示一个群聊。")
    def test_generate_group_image_critique_rejects_descriptive_llm_output(self, mock_call_ai):
        social = ImageSocialClassification("screenshot", "showoff", "text", 0.9, "screenshot")

        reply = _generate_group_image_critique_reply("截图里有大量聊天文字。", social, fallback="这截图味儿挺冲。")

        self.assertEqual(reply, "这截图味儿挺冲。")
        mock_call_ai.assert_called_once()

    def test_sanitize_vision_critique_rejects_description(self):
        self.assertEqual(_sanitize_vision_critique_reply("截图显示一个群聊。"), "")
        self.assertEqual(_sanitize_vision_critique_reply("有点东西。"), "")
        self.assertEqual(_sanitize_vision_critique_reply("这群名攻击性很强。"), "这群名攻击性很强。")

    @patch("apps.qq_ai_bridge.skills.image_understanding.call_ai", return_value="这聊天记录像事故现场。")
    def test_generate_group_image_critique_uses_llm_for_chat_record(self, mock_call_ai):
        social = ImageSocialClassification("chat_record", "showoff", "text", 0.9, "chat_record")

        reply = _generate_group_image_critique_reply(
            "图片中是一段群聊聊天记录，有几句对话。",
            social,
            fallback="看不懂喵",
        )

        self.assertEqual(reply, "这聊天记录像事故现场。")
        mock_call_ai.assert_called_once()

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.send_group_msg")
    @patch("apps.qq_ai_bridge.skills.image_understanding.call_ai", return_value="这包浆程度很深。")
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="这是一张搞笑梗图。")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("screenshot", "joke", "short_text", 0.88, "showoff", short_text="有梗。"),
    )
    def test_group_image_uses_reply_all_messages_trigger(
        self,
        _mock_social,
        mock_vision,
        mock_call_ai,
        mock_send_group_msg,
        _mock_append_log,
    ):
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
        mock_vision.assert_called_once()
        mock_call_ai.assert_called_once()
        mock_send_group_msg.assert_called_once()
        self.assertEqual(mock_send_group_msg.call_args.args[1], "这包浆程度很深。")
        self.assertEqual(mock_send_group_msg.call_args.kwargs["reply_to_message_id"], 5566)
        logged_payload = _mock_append_log.call_args.args[2]
        self.assertEqual(logged_payload["image_type"], "screenshot")
        self.assertEqual(logged_payload["social_intent"], "joke")

    @patch("apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social")
    def test_mention_only_group_image_requires_trigger(self, mock_social):
        skill = ImageUnderstandingSkill()
        context = self._group_image_context(message_id=5567)
        context.group_config = {"bot_can_reply": True, "enable_vision": True, "reply_all_messages": False}
        context.mentioned_self = False

        result = skill.handle(context)

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_social.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social")
    def test_mention_only_group_ai_prefix_image_does_not_trigger(self, mock_social):
        skill = ImageUnderstandingSkill()
        context = self._group_image_context(message_id=5568, text="ai 看图")
        context.group_config = {"bot_can_reply": True, "enable_vision": True, "reply_all_messages": False}
        context.mentioned_self = False

        result = skill.handle(context)

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_social.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.image_understanding.send_group_msg")
    @patch("apps.qq_ai_bridge.skills.image_understanding.call_ai", return_value="经典报错，血压上来了。")
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="这是一张截图，写着错误信息。")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("screenshot", "ask_identify", "full_text", 0.95, "identify_request", short_text="我先帮你看下。"),
    )
    def test_mention_only_group_real_mention_image_can_read(self, _mock_social, mock_vision, _mock_call_ai, mock_send):
        skill = ImageUnderstandingSkill()
        context = self._group_image_context(message_id=5569, text="帮我看图")
        context.group_config = {"bot_can_reply": True, "enable_vision": True, "reply_all_messages": False}
        context.mentioned_self = True

        result = skill.handle(context)

        self.assertTrue(result.handled)
        mock_vision.assert_called_once()
        mock_send.assert_called_once()

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.react_message_with_multiple_emojis", return_value={"ok": True, "emoji_names": ["laugh_cry"]})
    @patch("apps.qq_ai_bridge.skills.image_understanding._should_react_to_passive_low_info", return_value=True)
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("meme", "joke", "reaction", 0.9, "meme", short_text="有梗。", emoji_name="laugh_cry"),
    )
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="这是一张梗图")
    def test_group_image_reaction_path_skips_text_reply(
        self,
        mock_vision,
        _mock_social,
        _mock_sample,
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
        mock_vision.assert_called_once()
        self.assertTrue(mock_react.call_args.kwargs["preserve_order"])

    @patch("apps.qq_ai_bridge.skills.image_understanding.react_message_with_multiple_emojis", return_value={"ok": True, "emoji_names": ["red_button"]})
    @patch("apps.qq_ai_bridge.skills.image_understanding._should_react_to_passive_low_info", return_value=True)
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="图片中是一个蓝色标志")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button"),
    )
    def test_group_image_reaction_preserves_classifier_emoji(self, _mock_social, _mock_vision, _mock_sample, mock_react):
        skill = ImageUnderstandingSkill()
        context = SkillContext(
            data={"message_id": 7789},
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
            message_id=7789,
            nick="tester",
            raw_message="",
        )

        result = skill.handle(context)

        self.assertTrue(result.handled)
        mock_react.assert_called_once()
        self.assertEqual(mock_react.call_args.kwargs["preferred_order"][0], "red_button")
        self.assertTrue(mock_react.call_args.kwargs["preserve_order"])

    @patch("apps.qq_ai_bridge.skills.image_understanding.react_message_with_multiple_emojis", return_value={"ok": True, "emoji_names": ["lollipop"]})
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="图里是一只很可爱的猫")
    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button"),
    )
    def test_group_image_reaction_samples_vision_for_passive_image(self, _mock_social, mock_append_log, mock_vision, mock_react):
        skill = ImageUnderstandingSkill()
        context = SkillContext(
            data={"message_id": 7791},
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
            message_id=7791,
            nick="tester",
            raw_message="",
        )

        result = skill.handle(context)

        self.assertTrue(result.handled)
        mock_vision.assert_called_once()
        mock_react.assert_not_called()
        mock_append_log.assert_called_once()
        self.assertEqual(mock_append_log.call_args.args[2]["vision_summary"], "图里是一只很可爱的猫")
        self.assertEqual(mock_append_log.call_args.args[2]["source"], "image_understanding:no_reply")

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.send_group_msg")
    @patch("apps.qq_ai_bridge.skills.image_understanding.react_message_with_multiple_emojis")
    @patch("apps.qq_ai_bridge.skills.image_understanding.call_ai", return_value="这报错味儿太冲了。")
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="这是一张报错截图，里面有错误信息")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button"),
    )
    def test_group_image_reaction_reads_passive_screenshot_without_replying(
        self, _mock_social, mock_vision, mock_call_ai, mock_react, mock_send, _mock_log
    ):
        result = ImageUnderstandingSkill().handle(self._group_image_context(message_id=7792))

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_vision.assert_called_once()
        mock_call_ai.assert_not_called()
        mock_react.assert_not_called()
        mock_send.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.image_understanding.send_group_msg")
    @patch("apps.qq_ai_bridge.skills.image_understanding.react_message_with_multiple_emojis")
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="这图是个标志 我不太确定。")
    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button"),
    )
    def test_group_image_reaction_can_silence_uncertain_low_info_image(
        self, _mock_social, mock_append_log, mock_vision, mock_react, mock_send
    ):
        low_confidence_social = ImageSocialClassification("low_info", "showoff", "reaction", 0.49, "image_only", emoji_name="red_button")
        _mock_social.return_value = low_confidence_social
        result = ImageUnderstandingSkill().handle(self._group_image_context(message_id=7793))

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_vision.assert_called_once()
        mock_react.assert_not_called()
        mock_send.assert_not_called()
        mock_append_log.assert_called_once()
        self.assertEqual(mock_append_log.call_args.args[2]["source"], "image_understanding:no_reply")

    def test_uncertain_high_confidence_low_info_static_image_stays_silent(self):
        social = ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button")

        decision = _decide_group_image_action_from_vision_reply(
            "图片中是一个Q版角色，穿着粉色衣服，表情可爱。我不太确定。",
            has_user_text=False,
            force_reply=False,
            social=social,
        )

        self.assertEqual(decision.action, "no_reply")
        self.assertEqual(decision.reason, "passive_low_info_static_image")

    def test_passive_avatar_expression_stays_silent(self):
        social = ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button")

        decision = _decide_group_image_action_from_vision_reply(
            "这是一幅卡通风格的头像。看起来有点困惑呢。我不太确定。",
            has_user_text=False,
            force_reply=False,
            social=social,
        )

        self.assertEqual(decision.action, "no_reply")
        self.assertEqual(decision.reason, "passive_low_info_visual")

    def test_captioned_avatar_expression_stays_context_only(self):
        social = ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button")

        decision = _decide_group_image_action_from_vision_reply(
            "这是一幅卡通风格的头像。看起来有点困惑呢。我不太确定。",
            has_user_text=True,
            force_reply=False,
            social=social,
        )

        self.assertEqual(decision.action, "no_reply")
        self.assertEqual(decision.reason, "low_info_visual_context_only")

    def test_low_info_image_with_text_can_react(self):
        social = ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button")

        decision = _decide_group_image_action_from_vision_reply(
            "图片中是一个Q版角色，旁边有“抱操”字样。我不太确定。",
            has_user_text=False,
            force_reply=False,
            social=social,
        )

        self.assertEqual(decision.action, "reaction")
        self.assertEqual(decision.emoji_name, "lick_screen")

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.send_group_msg")
    @patch("apps.qq_ai_bridge.skills.image_understanding.react_message_with_multiple_emojis", return_value={"ok": True, "emoji_names": ["question"]})
    @patch("apps.qq_ai_bridge.skills.image_understanding._should_react_to_passive_low_info", return_value=True)
    @patch("apps.qq_ai_bridge.skills.image_understanding.call_ai", return_value="这头像味儿太正了。")
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="这是一幅卡通风格的头像。看起来有点困惑呢。我不太确定。")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("unknown", "unknown", "short_text", 0.42, "fallback_social_guess", short_text="何意味"),
    )
    def test_short_text_avatar_expression_does_not_call_critique_llm(
        self,
        _mock_social,
        mock_vision,
        mock_call_ai,
        _mock_sample,
        mock_react,
        mock_send,
        _mock_log,
    ):
        result = ImageUnderstandingSkill().handle(self._group_image_context(message_id=7796, text="哈哈"))

        self.assertTrue(result.handled)
        mock_vision.assert_called_once()
        mock_call_ai.assert_not_called()
        mock_react.assert_called_once()
        mock_send.assert_not_called()

    def test_uncertain_chat_record_passive_stays_silent(self):
        social = ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button")

        decision = _decide_group_image_action_from_vision_reply(
            "图片中是一段群聊聊天记录，有几句对话。我不太确定。",
            has_user_text=False,
            force_reply=False,
            social=social,
        )

        self.assertEqual(decision.action, "no_reply")
        self.assertEqual(decision.reason, "passive_screenshot_context_only")

    def test_captioned_chat_record_can_reply(self):
        social = ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button")

        decision = _decide_group_image_action_from_vision_reply(
            "图片中是一段群聊聊天记录，有几句对话。我不太确定。",
            has_user_text=True,
            force_reply=False,
            social=social,
        )

        self.assertEqual(decision.action, "text")
        self.assertEqual(decision.reason, "requested_or_captioned")

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.send_group_msg")
    @patch("apps.qq_ai_bridge.skills.image_understanding.react_message_with_multiple_emojis")
    @patch("apps.qq_ai_bridge.skills.image_understanding._should_react_to_passive_low_info", return_value=True)
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="图片显示DJGenji点赞了视频。视频被点赞了，开心！我不太确定。")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button"),
    )
    def test_group_captioned_like_image_uses_low_info_reaction_sample(
        self, _mock_social, mock_vision, _mock_sample, mock_react, mock_send, _mock_append_log
    ):
        result = ImageUnderstandingSkill().handle(self._group_image_context(message_id=7795, text="爸爸"))

        self.assertTrue(result.handled)
        mock_vision.assert_called_once()
        mock_react.assert_called_once()
        mock_send.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.send_group_msg")
    @patch("apps.qq_ai_bridge.skills.image_understanding.react_message_with_multiple_emojis", return_value={"ok": True, "emoji_names": ["lick_screen"]})
    @patch("apps.qq_ai_bridge.skills.image_understanding._should_react_to_passive_low_info", return_value=True)
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="图片中显示了两个人的手臂，其中一人穿着灰色上衣和黑色短裤。我不太确定。")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button"),
    )
    def test_group_image_reaction_prefers_lick_screen_for_body_hint(
        self, _mock_social, mock_vision, _mock_sample, mock_react, mock_send, mock_append_log
    ):
        result = ImageUnderstandingSkill().handle(self._group_image_context(message_id=7794))

        self.assertTrue(result.handled)
        mock_vision.assert_called_once()
        mock_react.assert_called_once()
        self.assertEqual(mock_react.call_args.kwargs["preferred_order"][0], "lick_screen")
        mock_send.assert_not_called()
        mock_append_log.assert_called_once()

    @patch("apps.qq_ai_bridge.skills.image_understanding.react_message_with_multiple_emojis", return_value={"ok": True, "emoji_names": ["red_button"]})
    @patch("apps.qq_ai_bridge.skills.image_understanding._should_react_to_passive_low_info", return_value=True)
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="这是一张搞笑梗图")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button"),
    )
    def test_group_image_reaction_respects_passive_read_interval(self, _mock_social, mock_vision, _mock_sample, mock_react):
        _LAST_GROUP_VISION_REPLY_TS[str(810938203)] = 9999999999
        _LAST_GROUP_VISION_READ_TS[str(810938203)] = 9999999999
        skill = ImageUnderstandingSkill()
        context = SkillContext(
            data={"message_id": 7790},
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
            message_id=7790,
            nick="tester",
            raw_message="",
        )

        result = skill.handle(context)

        self.assertTrue(result.handled)
        mock_vision.assert_not_called()
        mock_react.assert_called_once()

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.send_group_msg")
    @patch("apps.qq_ai_bridge.skills.image_understanding.call_ai")
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("screenshot", "ask_identify", "full_text", 0.95, "identify_request", short_text="我先帮你看下。"),
    )
    def test_global_passive_full_text_image_respects_read_interval(
        self,
        _mock_social,
        mock_vision,
        mock_call_ai,
        mock_send,
        mock_append_log,
    ):
        _LAST_GROUP_VISION_READ_TS[str(810938203)] = 9999999999

        result = ImageUnderstandingSkill().handle(self._group_image_context(message_id=7797))

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_vision.assert_not_called()
        mock_call_ai.assert_not_called()
        mock_send.assert_not_called()
        mock_append_log.assert_not_called()

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.call_ai")
    @patch("apps.qq_ai_bridge.skills.image_understanding.react_message_with_multiple_emojis")
    @patch("apps.qq_ai_bridge.skills.image_understanding._should_react_to_passive_low_info", return_value=False)
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("low_info", "showoff", "reaction", 0.69, "image_only", emoji_name="red_button"),
    )
    def test_global_passive_low_info_reaction_sample_can_silence_without_llm(
        self,
        _mock_social,
        mock_vision,
        _mock_sample,
        mock_react,
        mock_call_ai,
        mock_append_log,
    ):
        _LAST_GROUP_VISION_READ_TS[str(810938203)] = 9999999999

        result = ImageUnderstandingSkill().handle(self._group_image_context(message_id=7798))

        self.assertTrue(result.handled)
        self.assertEqual(result.status, "ignore")
        mock_vision.assert_not_called()
        mock_react.assert_not_called()
        mock_call_ai.assert_not_called()
        mock_append_log.assert_called_once()

    @patch("apps.qq_ai_bridge.skills.image_understanding.append_group_chat_log")
    @patch("apps.qq_ai_bridge.skills.image_understanding.send_group_msg")
    @patch("apps.qq_ai_bridge.skills.image_understanding.call_ai", return_value="经典报错，血压上来了。")
    @patch("apps.qq_ai_bridge.skills.image_understanding.run_vision_pipeline", return_value="这是一张截图，写着错误信息。")
    @patch(
        "apps.qq_ai_bridge.skills.image_understanding.classify_group_image_social",
        return_value=ImageSocialClassification("screenshot", "ask_identify", "full_text", 0.95, "identify_request", short_text="我先帮你看下。"),
    )
    def test_group_image_full_text_path_uses_vision(
        self,
        _mock_social,
        mock_vision,
        _mock_call_ai,
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
