import importlib
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "qq-ai-bridge")


class KimiConfigDefaultsTests(unittest.TestCase):
    def test_settings_default_kimi_model_is_kimi_k26(self):
        import apps.qq_ai_bridge.config.settings as settings

        original_env = os.environ.get("KIMI_MODEL")
        try:
            with patch.dict(os.environ, {"KIMI_MODEL": ""}, clear=False):
                reloaded = importlib.reload(settings)
                self.assertEqual(reloaded.KIMI_MODEL, "kimi-k2.6")
        finally:
            if original_env is None:
                os.environ.pop("KIMI_MODEL", None)
            else:
                os.environ["KIMI_MODEL"] = original_env
            importlib.reload(settings)

    def test_env_example_uses_kimi_k26_for_text_and_vision(self):
        text = Path("qq-ai-bridge/.env.example").read_text(encoding="utf-8")

        self.assertIn("KIMI_MODEL=kimi-k2.6", text)
        self.assertIn("VISION_MODEL=kimi-k2.6", text)
        self.assertNotIn("KIMI_MODEL=moonshot-v1-32k", text)
        self.assertNotIn("VISION_MODEL=your_vision_model_here", text)


if __name__ == "__main__":
    unittest.main()
