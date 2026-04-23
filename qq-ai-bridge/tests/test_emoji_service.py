import sys
import unittest

sys.path.insert(0, "qq-ai-bridge")

from apps.qq_ai_bridge.services.emoji_service import (
    build_face_cq,
    extract_emoji_name,
    is_emoji_request,
    pick_face_cq,
)


class EmojiServiceTests(unittest.TestCase):
    def test_is_emoji_request(self):
        self.assertTrue(is_emoji_request("给我贴个表情"))
        self.assertTrue(is_emoji_request("来个emoji"))
        self.assertFalse(is_emoji_request("今天天气不错"))

    def test_extract_emoji_name(self):
        self.assertEqual(extract_emoji_name("来个笑哭"), "笑哭")
        self.assertEqual(extract_emoji_name("发个棒棒糖表情"), "棒棒糖")
        self.assertIsNone(extract_emoji_name("来个未知表情"))

    def test_build_face_cq(self):
        self.assertEqual(build_face_cq("笑哭"), "[CQ:face,id=182]")
        self.assertIsNone(build_face_cq("不存在"))

    def test_pick_face_cq(self):
        name, cq = pick_face_cq(seed="user:1")
        self.assertTrue(name)
        self.assertTrue(cq.startswith("[CQ:face,id="))


if __name__ == "__main__":
    unittest.main()
