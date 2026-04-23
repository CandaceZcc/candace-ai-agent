"""HTTP API route registration for pc-agent."""

from flask import jsonify, request

from apps.pc_agent.browser.chrome import launch_and_open, launch_chrome, open_url
from apps.pc_agent.browser.service import get_browser_health, get_browser_runtime
from apps.pc_agent.desktop.keyboard import hotkey, press_key, type_text
from apps.pc_agent.desktop.mouse import click, double_click, move, position, right_click, scroll
from apps.pc_agent.desktop.ocr import click_text, find_text
from apps.pc_agent.desktop.screen import ocr_screen, screen_size, screenshot


_SESSION_STATE: dict[int, dict] = {}


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

    @app.route("/observe", methods=["POST"])
    def observe_route():
        _ = request.get_json(force=True)
        return jsonify(ocr_screen())

    @app.route("/session/get", methods=["POST"])
    def session_get_route():
        data = request.get_json(force=True)
        user_id = int(data.get("user_id", 0))
        session = _SESSION_STATE.get(user_id, {})
        return jsonify({"status": "ok", "session": session})

    @app.route("/session/reset", methods=["POST"])
    def session_reset_route():
        data = request.get_json(force=True)
        user_id = int(data.get("user_id", 0))
        _SESSION_STATE.pop(user_id, None)
        return jsonify({"status": "ok", "user_id": user_id, "message": "session reset"})

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

    @app.route("/browser/health", methods=["GET"])
    def browser_health_route():
        start_runtime = str(request.args.get("start", "")).lower() in {"1", "true", "yes"}
        payload = get_browser_health(start_runtime=start_runtime)
        status = 200 if payload.get("status") == "ok" else 500
        return jsonify(payload), status

    @app.route("/browser/open_url", methods=["POST"])
    def browser_open_url_route():
        data = request.get_json(force=True)
        runtime = get_browser_runtime()
        return jsonify(
            runtime.open_url(
                data["url"],
                wait_until=str(data.get("wait_until", "domcontentloaded")),
                new_tab=bool(data.get("new_tab", False)),
            )
        )

    @app.route("/browser/ocr", methods=["GET"])
    def browser_ocr_route():
        runtime = get_browser_runtime()
        return jsonify(runtime.ocr())

    @app.route("/browser/find_text", methods=["POST"])
    def browser_find_text_route():
        data = request.get_json(force=True)
        runtime = get_browser_runtime()
        result = runtime.find_text(data)
        status = 200 if result.get("status") in {"ok", "not_found"} else 400
        return jsonify(result), status

    @app.route("/browser/click_text", methods=["POST"])
    def browser_click_text_route():
        data = request.get_json(force=True)
        runtime = get_browser_runtime()
        result = runtime.click_text(data)
        status = 200 if result.get("status") in {"ok", "not_found"} else 400
        return jsonify(result), status

    @app.route("/browser/extract_deadline", methods=["POST"])
    def browser_extract_deadline_route():
        _ = request.get_json(silent=True) or {}
        runtime = get_browser_runtime()
        return jsonify(runtime.extract_deadline())

    @app.route("/browser/screenshot", methods=["POST"])
    def browser_screenshot_route():
        data = request.get_json(silent=True) or {}
        runtime = get_browser_runtime()
        return jsonify(runtime.screenshot(full_page=bool(data.get("full_page", False))))

    return app


__all__ = ["register_routes"]
