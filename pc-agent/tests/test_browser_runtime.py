import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

for module_name in list(sys.modules):
    if module_name == "apps" or module_name.startswith("apps."):
        del sys.modules[module_name]

sys.path.insert(0, "pc-agent")

try:
    from apps.pc_agent.browser import service as browser_service
    from apps.pc_agent.browser.playwright_runtime import PlaywrightRuntime
    IMPORT_ERROR = None
except Exception as exc:  # pragma: no cover - environment dependent
    browser_service = None
    PlaywrightRuntime = None
    IMPORT_ERROR = exc


@unittest.skipIf(IMPORT_ERROR is not None, f"pc-agent browser deps unavailable: {IMPORT_ERROR}")
class BrowserServiceTests(unittest.TestCase):
    def test_resolve_profile_dir_migrates_legacy_profile(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            new_dir = Path(tmpdir) / "new-profile"
            legacy_dir = Path(tmpdir) / "legacy-profile"
            legacy_dir.mkdir(parents=True, exist_ok=True)
            (legacy_dir / "Cookies").write_text("cookie-data", encoding="utf-8")

            with patch.object(browser_service, "PLAYWRIGHT_PROFILE_DIR", str(new_dir)), patch.object(
                browser_service,
                "PLAYWRIGHT_LEGACY_PROFILE_DIR",
                str(legacy_dir),
            ):
                resolution = browser_service.resolve_profile_dir()

            self.assertEqual(resolution.status, "migrated")
            self.assertTrue((new_dir / "Cookies").exists())

    def test_browser_health_without_startup_is_stable(self):
        resolution = browser_service.ProfileResolution(
            profile_dir="/tmp/browser-profile",
            legacy_profile_dir="/tmp/legacy-browser-profile",
            status="ok",
            message="ready",
        )
        with patch.object(browser_service, "_runtime", None), patch.object(
            browser_service,
            "get_profile_resolution",
            return_value=resolution,
        ):
            health = browser_service.get_browser_health(start_runtime=False)

        self.assertEqual(health["status"], "ok")
        self.assertFalse(health["started"])
        self.assertEqual(health["profile_dir"], "/tmp/browser-profile")


@unittest.skipIf(IMPORT_ERROR is not None, f"pc-agent browser deps unavailable: {IMPORT_ERROR}")
class BrowserRuntimeTests(unittest.TestCase):
    def test_extract_deadline_returns_keyword_matches(self):
        runtime = PlaywrightRuntime(profile_dir="/tmp/test-browser-profile")

        class FakePage:
            def title(self):
                return "Portal Dashboard"

        runtime._page = FakePage()
        runtime._context = object()

        with patch.object(
            runtime,
            "_ensure_page",
            return_value=runtime._page,
        ), patch.object(
            runtime,
            "ocr",
            return_value={
                "status": "ok",
                "text": "Math Assignment due tomorrow\nRandom note\n截止时间 周五 18:00",
                "source": "page_text",
            },
        ):
            result = runtime.extract_deadline()

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["items"][0]["matched_keyword"], "due")


if __name__ == "__main__":
    unittest.main()
