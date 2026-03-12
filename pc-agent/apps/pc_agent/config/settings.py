"""pc-agent runtime settings."""

import os

PC_AGENT_PORT = int(os.environ.get("PC_AGENT_PORT", 5050))
PLAYWRIGHT_PROFILE_DIR = os.environ.get(
    "PC_AGENT_PLAYWRIGHT_PROFILE_DIR",
    os.path.expanduser("~/.cache/pc-agent/playwright-profile"),
)
PLAYWRIGHT_HEADLESS = os.environ.get("PC_AGENT_PLAYWRIGHT_HEADLESS", "").lower() in {"1", "true", "yes"}
PLAYWRIGHT_SCREENSHOT_DIR = os.environ.get(
    "PC_AGENT_PLAYWRIGHT_SCREENSHOT_DIR",
    os.path.expanduser("~/pc-agent-playwright-shots"),
)
