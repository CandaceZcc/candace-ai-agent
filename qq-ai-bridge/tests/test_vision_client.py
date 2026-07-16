import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from PIL import Image

sys.path.insert(0, "qq-ai-bridge")

from vision.client import _prepare_image_for_vision, analyze_image_with_details


class VisionClientTests(unittest.TestCase):
    @patch.dict(
        os.environ,
        {
            "VISION_API_URL": (
                "https://right.codes/gemini/v1beta/models/"
                "gemini-3-flash-preview:generateContent"
            ),
            "VISION_API_KEY": "sk-test",
            "VISION_MODEL": "gemini-3-flash-preview",
        },
        clear=False,
    )
    @patch("vision.client.requests.post")
    def test_analyze_image_uses_gemini_native_request_and_response(self, mock_post):
        response = MagicMock()
        response.ok = True
        response.status_code = 200
        response.text = '{"candidates":[]}'
        response.json.return_value = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"text": "图里是一只橘猫。"},
                        ]
                    }
                }
            ]
        }
        mock_post.return_value = response

        with tempfile.TemporaryDirectory() as tmp_dir:
            image_path = os.path.join(tmp_dir, "cat.png")
            Image.new("RGB", (16, 16), color=(255, 128, 0)).save(image_path)

            result = analyze_image_with_details(image_path, user_text="这是什么")

        self.assertEqual(result.status, "ok")
        self.assertEqual(result.content, "图里是一只橘猫。")
        request_kwargs = mock_post.call_args.kwargs
        self.assertEqual(request_kwargs["headers"]["x-goog-api-key"], "sk-test")
        self.assertNotIn("Authorization", request_kwargs["headers"])
        payload = request_kwargs["json"]
        self.assertNotIn("messages", payload)
        parts = payload["contents"][0]["parts"]
        self.assertEqual(parts[0]["text"].splitlines()[-1], "用户补充：这是什么")
        self.assertEqual(parts[1]["inline_data"]["mime_type"], "image/jpeg")
        self.assertTrue(parts[1]["inline_data"]["data"])

    def test_prepare_image_for_vision_converts_gif_to_jpg(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            gif_path = os.path.join(tmp_dir, "anim.gif")
            frame_1 = Image.new("RGB", (16, 16), color=(255, 0, 0))
            frame_2 = Image.new("RGB", (16, 16), color=(0, 255, 0))
            frame_1.save(gif_path, save_all=True, append_images=[frame_2], format="GIF", duration=100, loop=0)

            prepared_path, should_cleanup = _prepare_image_for_vision(gif_path)

            self.assertTrue(should_cleanup)
            self.assertTrue(prepared_path.endswith(".jpg"))
            self.assertTrue(os.path.exists(prepared_path))
            with Image.open(prepared_path) as prepared:
                self.assertEqual(prepared.format, "JPEG")
                self.assertEqual(prepared.size, (16, 16))


if __name__ == "__main__":
    unittest.main()
