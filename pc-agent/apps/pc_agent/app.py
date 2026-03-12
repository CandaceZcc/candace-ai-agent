"""pc-agent application entrypoint."""

from flask import Flask
import pyautogui

from apps.pc_agent.adapters.http_api import register_routes


def create_app() -> Flask:
    """Create and configure the pc-agent Flask app."""
    app = Flask(__name__)
    pyautogui.FAILSAFE = True
    pyautogui.PAUSE = 0.08
    register_routes(app)
    return app


app = create_app()

__all__ = ["app", "create_app"]
