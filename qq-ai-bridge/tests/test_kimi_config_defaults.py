import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")


class KimiConfigDefaultsTests(unittest.TestCase):
    def test_settings_default_kimi_model_is_deepseek_v4_flash(self):
        import apps.qq_ai_bridge.config.settings as settings

        original_env = os.environ.get("KIMI_MODEL")
        try:
            with patch.dict(os.environ, {"KIMI_MODEL": ""}, clear=False):
                reloaded = importlib.reload(settings)
                self.assertEqual(reloaded.KIMI_MODEL, "deepseek-v4-flash")
                self.assertEqual(reloaded.KIMI_BASE_URL, "https://api.deepseek.com")
        finally:
            if original_env is None:
                os.environ.pop("KIMI_MODEL", None)
            else:
                os.environ["KIMI_MODEL"] = original_env
            importlib.reload(settings)

    def test_env_example_uses_deepseek_text_gemini_vision_and_draw(self):
        text = Path("qq-ai-bridge/.env.example").read_text(encoding="utf-8")

        self.assertIn("KIMI_MODEL=deepseek-v4-flash", text)
        self.assertIn("KIMI_BASE_URL=https://api.deepseek.com", text)
        self.assertIn("LLM_BACKEND=auto", text)
        self.assertIn("LLM_MAX_CONCURRENCY=4", text)
        self.assertIn(
            "VISION_API_URL=https://right.codes/gemini/v1beta/models/"
            "gemini-3-flash-preview:generateContent",
            text,
        )
        self.assertIn("VISION_API_KEY=\n", text)
        self.assertIn("VISION_MODEL=gemini-3-flash-preview", text)
        self.assertIn("DRAW_API_KEY=\n", text)
        self.assertIn("DRAW_BASE_URL=https://www.right.codes", text)
        self.assertIn("DRAW_MODEL=nano-banana-2", text)
        self.assertIn("DRAW_ASPECT_RATIO=1:1", text)
        self.assertIn("DRAW_IMAGE_SIZE=1K", text)
        self.assertIn("DRAW_POLL_INTERVAL_SECONDS=2", text)
        self.assertIn("DRAW_TIMEOUT_SECONDS=240", text)
        self.assertIn("DRAW_POLL_MAX_TRANSIENT_ERRORS=6", text)
        self.assertIn("DRAW_FALLBACK_MODEL=gpt-image-2", text)
        self.assertIn("DRAW_FALLBACK_ENABLED=true", text)
        self.assertNotIn("KIMI_MODEL=moonshot-v1-32k", text)
        self.assertNotIn("VISION_MODEL=your_vision_model_here", text)

    def test_settings_default_draw_configuration(self):
        import apps.qq_ai_bridge.config.settings as settings

        env_names = (
            "DRAW_API_KEY",
            "VISION_API_KEY",
            "DRAW_BASE_URL",
            "DRAW_MODEL",
            "DRAW_ASPECT_RATIO",
            "DRAW_IMAGE_SIZE",
            "DRAW_POLL_INTERVAL_SECONDS",
            "DRAW_TIMEOUT_SECONDS",
            "DRAW_POLL_MAX_TRANSIENT_ERRORS",
            "DRAW_FALLBACK_MODEL",
            "DRAW_FALLBACK_ENABLED",
        )
        original = {name: os.environ.get(name) for name in env_names}
        try:
            with patch.dict(os.environ, {name: "" for name in env_names}, clear=False):
                reloaded = importlib.reload(settings)
                self.assertEqual(reloaded.DRAW_API_KEY, "")
                self.assertEqual(reloaded.DRAW_BASE_URL, "https://www.right.codes")
                self.assertEqual(reloaded.DRAW_MODEL, "nano-banana-2")
                self.assertEqual(reloaded.DRAW_ASPECT_RATIO, "1:1")
                self.assertEqual(reloaded.DRAW_IMAGE_SIZE, "1K")
                self.assertEqual(reloaded.DRAW_POLL_INTERVAL_SECONDS, 2)
                self.assertEqual(reloaded.DRAW_TIMEOUT_SECONDS, 240)
                self.assertEqual(reloaded.DRAW_POLL_MAX_TRANSIENT_ERRORS, 6)
                self.assertEqual(reloaded.DRAW_FALLBACK_MODEL, "gpt-image-2")
                self.assertTrue(reloaded.DRAW_FALLBACK_ENABLED)
        finally:
            for name, value in original.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
            importlib.reload(settings)


if __name__ == "__main__":
    unittest.main()
