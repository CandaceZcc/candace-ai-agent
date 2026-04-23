"""Service boundary for persistent Playwright browser runtime access."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass

from apps.pc_agent.browser.playwright_runtime import PlaywrightRuntime
from apps.pc_agent.config.settings import (
    PLAYWRIGHT_HEADLESS,
    PLAYWRIGHT_LEGACY_PROFILE_DIR,
    PLAYWRIGHT_PROFILE_DIR,
    PLAYWRIGHT_SCREENSHOT_DIR,
)

_runtime: PlaywrightRuntime | None = None
_profile_resolution: "ProfileResolution | None" = None


@dataclass
class ProfileResolution:
    """Describe which browser profile path was chosen and why."""

    profile_dir: str
    legacy_profile_dir: str
    status: str
    message: str
    migrated: bool = False


def resolve_profile_dir() -> ProfileResolution:
    """Resolve the active profile directory with one-time legacy migration."""
    new_dir = os.path.abspath(os.path.expanduser(PLAYWRIGHT_PROFILE_DIR))
    legacy_dir = os.path.abspath(os.path.expanduser(PLAYWRIGHT_LEGACY_PROFILE_DIR))

    if os.path.isdir(new_dir) and any(os.scandir(new_dir)):
        return ProfileResolution(
            profile_dir=new_dir,
            legacy_profile_dir=legacy_dir,
            status="ok",
            message="Using configured browser profile.",
        )

    if new_dir != legacy_dir and os.path.isdir(legacy_dir) and any(os.scandir(legacy_dir)):
        os.makedirs(os.path.dirname(new_dir), exist_ok=True)
        if not os.path.exists(new_dir):
            shutil.copytree(legacy_dir, new_dir)
            return ProfileResolution(
                profile_dir=new_dir,
                legacy_profile_dir=legacy_dir,
                status="migrated",
                message="Migrated legacy browser profile to the new path.",
                migrated=True,
            )
        return ProfileResolution(
            profile_dir=new_dir,
            legacy_profile_dir=legacy_dir,
            status="warning",
            message="Legacy browser profile exists but new path is already present; using new path.",
        )

    os.makedirs(new_dir, exist_ok=True)
    return ProfileResolution(
        profile_dir=new_dir,
        legacy_profile_dir=legacy_dir,
        status="created",
        message="Created browser profile directory.",
    )


def get_browser_runtime() -> PlaywrightRuntime:
    """Return a singleton Playwright runtime configured for this machine."""
    global _profile_resolution, _runtime
    if _runtime is None:
        _profile_resolution = resolve_profile_dir()
        _runtime = PlaywrightRuntime(
            profile_dir=_profile_resolution.profile_dir,
            headless=PLAYWRIGHT_HEADLESS,
            screenshot_dir=PLAYWRIGHT_SCREENSHOT_DIR,
        )
    return _runtime


def get_profile_resolution() -> ProfileResolution:
    """Return cached profile-resolution metadata."""
    global _profile_resolution
    if _profile_resolution is None:
        _profile_resolution = resolve_profile_dir()
    return _profile_resolution


def get_browser_health(start_runtime: bool = False) -> dict:
    """Return browser runtime health without forcing startup by default."""
    resolution = get_profile_resolution()
    runtime = _runtime
    if start_runtime:
        runtime = get_browser_runtime()

    try:
        runtime_health = runtime.health() if runtime is not None else {
            "started": False,
            "headless": PLAYWRIGHT_HEADLESS,
            "active_tab_url": "",
            "tab_count": 0,
        }
        return {
            "status": "ok",
            "profile_dir": resolution.profile_dir,
            "legacy_profile_dir": resolution.legacy_profile_dir,
            "profile_status": resolution.status,
            "message": resolution.message,
            **runtime_health,
        }
    except Exception as exc:
        return {
            "status": "error",
            "reason": str(exc),
            "profile_dir": resolution.profile_dir,
            "legacy_profile_dir": resolution.legacy_profile_dir,
            "profile_status": resolution.status,
            "message": resolution.message,
            "started": False,
            "headless": PLAYWRIGHT_HEADLESS,
            "active_tab_url": "",
            "tab_count": 0,
        }


def reset_browser_runtime() -> None:
    """Dispose of the singleton runtime."""
    global _runtime
    if _runtime is not None:
        _runtime.close()
        _runtime = None


__all__ = [
    "ProfileResolution",
    "get_browser_health",
    "get_browser_runtime",
    "get_profile_resolution",
    "reset_browser_runtime",
]
