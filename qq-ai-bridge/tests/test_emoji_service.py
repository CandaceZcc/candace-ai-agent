import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.emoji_service import (
    build_face_sequence,
    build_face_cq,
    detect_emoji_request_count,
    extract_emoji_name,
    infer_reaction_preferred_order,
    is_emoji_request,
    is_face_fallback_request,
    is_message_reaction_request,
    pick_face_cq,
)


class EmojiServiceTests(unittest.TestCase):
    def test_is_emoji_request(self):
        self.assertTrue(is_emoji_request("给我贴个表情"))
        self.assertTrue(is_emoji_request("来个emoji"))
        self.assertTrue(is_emoji_request("来一个emoji"))
        self.assertFalse(is_emoji_request("今天天气不错"))

    def test_face_fallback_request_requires_named_emoji(self):
        self.assertFalse(is_face_fallback_request("给我贴个表情"))
        self.assertFalse(is_face_fallback_request("来个emoji"))
        self.assertTrue(is_face_fallback_request("给我贴个笑哭表情"))
        self.assertTrue(is_face_fallback_request("来个西瓜"))

    def test_message_reaction_request_is_explicit(self):
        self.assertFalse(is_message_reaction_request("给我贴个表情"))
        self.assertFalse(is_message_reaction_request("来一个emoji"))
        self.assertTrue(is_message_reaction_request("给这条消息点个表情"))
        self.assertTrue(is_message_reaction_request("消息上面多贴几个表情"))

    def test_extract_emoji_name(self):
        self.assertEqual(extract_emoji_name("来个笑哭"), "笑哭")
        self.assertEqual(extract_emoji_name("发个棒棒糖表情"), "棒棒糖")
        self.assertEqual(extract_emoji_name("给我来个doge"), "doge")
        self.assertEqual(extract_emoji_name("这话题爆了，给我贴个续标识"), "续标识")
        self.assertEqual(extract_emoji_name("太色了来个舔屏"), "舔屏")
        self.assertEqual(extract_emoji_name("来个西瓜"), "西瓜")
        self.assertEqual(extract_emoji_name("来个尴尬"), "尴尬")
        self.assertEqual(extract_emoji_name("来个惊讶"), "惊讶")
        self.assertIsNone(extract_emoji_name("来个未知表情"))

    def test_build_face_cq(self):
        self.assertEqual(build_face_cq("笑哭"), "[CQ:face,id=182]")
        self.assertEqual(build_face_cq("西瓜"), "[CQ:face,id=89]")
        self.assertEqual(build_face_cq("赞"), "[CQ:face,id=76]")
        self.assertEqual(build_face_cq("疑问"), "[CQ:face,id=32]")
        self.assertEqual(build_face_cq("舔屏"), "[CQ:face,id=339]")
        self.assertEqual(build_face_cq("续标识"), "[CQ:face,id=424]")
        self.assertIsNone(build_face_cq("不存在"))

    def test_pick_face_cq(self):
        name, cq = pick_face_cq(seed="user:1")
        self.assertTrue(name)
        self.assertTrue(cq.startswith("[CQ:face,id="))

    def test_detect_emoji_request_count(self):
        self.assertEqual(detect_emoji_request_count("给我贴几个表情"), 2)
        self.assertEqual(detect_emoji_request_count("贴3个表情"), 3)
        self.assertEqual(detect_emoji_request_count("贴两次"), 2)
        self.assertEqual(detect_emoji_request_count("贴10个表情"), 4)

    def test_build_face_sequence(self):
        seq = build_face_sequence(seed="u:1", count=3)
        self.assertEqual(len(seq), 3)
        self.assertTrue(all(item.startswith("[CQ:face,id=") for item in seq))

    def test_infer_reaction_preferred_order_hard_rules(self):
        self.assertEqual(
            infer_reaction_preferred_order("这个政治话题要爆了")[0],
            "button_marker",
        )
        self.assertEqual(
            infer_reaction_preferred_order("这波男女对立又开团了")[0],
            "button_marker",
        )
        self.assertEqual(
            infer_reaction_preferred_order("这也太色了我想舔屏")[0],
            "lick_screen",
        )
        self.assertEqual(
            infer_reaction_preferred_order("这个擦边图有点想冲了")[0],
            "lick_screen",
        )

    def test_infer_reaction_preferred_order_explicit_button(self):
        self.assertEqual(infer_reaction_preferred_order("能贴按按钮吗")[0], "button_marker")
        self.assertEqual(infer_reaction_preferred_order("给我贴个续标识")[0], "button_marker")

    def test_infer_reaction_preferred_order_more_explicit_emojis(self):
        self.assertEqual(infer_reaction_preferred_order("贴个西瓜")[0], "watermelon")
        self.assertEqual(infer_reaction_preferred_order("贴个尴尬")[0], "awkward")
        self.assertEqual(infer_reaction_preferred_order("贴个惊讶")[0], "surprised")

    def test_infer_reaction_default_order_is_not_laugh_cry_first(self):
        order = infer_reaction_preferred_order("普通聊天")

        self.assertNotEqual(order[0], "laugh_cry")
        self.assertIn("laugh_cry", order)

    def test_infer_reaction_keeps_explicit_laugh_cry_request(self):
        self.assertEqual(infer_reaction_preferred_order("给这条消息贴个笑哭")[0], "laugh_cry")

    def test_infer_reaction_contextual_goodnight_and_question(self):
        self.assertEqual(infer_reaction_preferred_order("晚安我先睡了")[0], "lollipop")
        self.assertEqual(infer_reaction_preferred_order("这是什么情况？")[0], "question")


if __name__ == "__main__":
    unittest.main()
