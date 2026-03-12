"""HTTP API route registration for pc-agent."""

from flask import jsonify, request

from apps.pc_agent.browser.chrome import launch_and_open, launch_chrome, open_url
from apps.pc_agent.desktop.keyboard import hotkey, press_key, type_text
from apps.pc_agent.desktop.mouse import click, double_click, move, position, right_click, scroll
from apps.pc_agent.desktop.ocr import click_text, find_text
from apps.pc_agent.desktop.screen import ocr_screen, screen_size, screenshot


def register_routes(app):
    """Register all pc-agent HTTP routes on the provided Flask app."""

    @app.route("/", methods=["GET"])
    def home():
        return jsonify({"status": "ok", "message": "pc-agent is running"})

    @app.route("/move", methods=["POST"])
    def move_route():
        data = request.get_json(force=True)
        return jsonify(move(data["x"], data["y"], data.get("duration", 0.0)))

    @app.route("/scroll", methods=["POST"])
    def scroll_route():
        data = request.get_json(force=True)
        return jsonify(scroll(data.get("clicks", -500), data.get("x"), data.get("y"), data.get("method", "auto")))

    @app.route("/click", methods=["POST"])
    def click_route():
        data = request.get_json(force=True)
        return jsonify(click(data["x"], data["y"], data.get("button", "left"), data.get("clicks", 1)))

    @app.route("/double_click", methods=["POST"])
    def double_click_route():
        data = request.get_json(force=True)
        return jsonify(double_click(data["x"], data["y"]))

    @app.route("/right_click", methods=["POST"])
    def right_click_route():
        data = request.get_json(force=True)
        return jsonify(right_click(data["x"], data["y"]))

    @app.route("/type", methods=["POST"])
    def type_route():
        data = request.get_json(force=True)
        return jsonify(type_text(data["text"], data.get("interval", 0.03)))

    @app.route("/press", methods=["POST"])
    def press_route():
        data = request.get_json(force=True)
        return jsonify(press_key(data["key"], data.get("presses", 1)))

    @app.route("/hotkey", methods=["POST"])
    def hotkey_route():
        data = request.get_json(force=True)
        result = hotkey(data["keys"])
        if isinstance(result, tuple):
            payload, status = result
            return jsonify(payload), status
        return jsonify(result)

    @app.route("/position", methods=["GET"])
    def position_route():
        return jsonify(position())

    @app.route("/screen_size", methods=["GET"])
    def screen_size_route():
        return jsonify(screen_size())

    @app.route("/screenshot", methods=["GET"])
    def screenshot_route():
        return jsonify(screenshot())

    @app.route("/ping", methods=["GET"])
    def ping():
        return jsonify({"status": "ok", "pong": True})

    @app.route("/open_url", methods=["POST"])
    def open_url_route():
        data = request.get_json(force=True)
        return jsonify(open_url(data["url"]))

    @app.route("/ocr", methods=["GET"])
    def ocr_route():
        return jsonify(ocr_screen())

    @app.route("/wait", methods=["POST"])
    def wait_route():
        import time
        data = request.get_json(force=True)
        seconds = float(data.get("seconds", 1.0))
        seconds = max(0.0, min(seconds, 10.0))
        time.sleep(seconds)
        return jsonify({"status": "ok", "action": "wait", "seconds": seconds})

    @app.route("/find_text", methods=["POST"])
    def find_text_route():
        data = request.get_json(force=True)
        result = find_text(data)
        if isinstance(result, tuple):
            payload, status = result
            return jsonify(payload), status
        return jsonify(result)

    @app.route("/click_text", methods=["POST"])
    def click_text_route():
        data = request.get_json(force=True)
        result = click_text(data)
        if isinstance(result, tuple):
            payload, status = result
            return jsonify(payload), status
        return jsonify(result)

    @app.route("/launch_chrome", methods=["POST"])
    def launch_chrome_route():
        return jsonify(launch_chrome())

    @app.route("/launch_and_open", methods=["POST"])
    def launch_and_open_route():
        data = request.get_json(force=True)
        return jsonify(launch_and_open(data["url"]))

    return app


__all__ = ["register_routes"]
