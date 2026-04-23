import os
import sys
import tempfile
import unittest

from PIL import Image

sys.path.insert(0, "qq-ai-bridge")

from vision.client import _prepare_image_for_vision


class VisionClientTests(unittest.TestCase):
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
