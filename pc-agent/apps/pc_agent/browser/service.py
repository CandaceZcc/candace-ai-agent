"""Service boundary for persistent Playwright browser runtime access."""

from __future__ import annotations

from apps.pc_agent.browser.playwright_runtime import PlaywrightRuntime
from apps.pc_agent.config.settings import (
    PLAYWRIGHT_HEADLESS,
    PLAYWRIGHT_PROFILE_DIR,
    PLAYWRIGHT_SCREENSHOT_DIR,
)

_runtime: PlaywrightRuntime | None = None


def get_browser_runtime() -> PlaywrightRuntime:
    """Return a singleton Playwright runtime configured for this machine."""
    global _runtime
    if _runtime is None:
        _runtime = PlaywrightRuntime(
            profile_dir=PLAYWRIGHT_PROFILE_DIR,
            headless=PLAYWRIGHT_HEADLESS,
            screenshot_dir=PLAYWRIGHT_SCREENSHOT_DIR,
        )
    return _runtime


def reset_browser_runtime() -> None:
    """Dispose of the singleton runtime."""
    global _runtime
    if _runtime is not None:
        _runtime.close()
        _runtime = None


__all__ = ["get_browser_runtime", "reset_browser_runtime"]
