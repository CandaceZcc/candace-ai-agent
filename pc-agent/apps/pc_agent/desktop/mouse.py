"""Mouse automation helpers for pc-agent."""

import time

import pyautogui


def perform_click(x: int, y: int, button: str = "left", clicks: int = 1, move_duration: float = 0.12):
    """Move to a point and perform a reliable mouse click sequence."""
    pyautogui.moveTo(x, y, duration=move_duration)
    time.sleep(0.08)
    for _ in range(max(1, clicks)):
        pyautogui.mouseDown(x=x, y=y, button=button)
        time.sleep(0.05)
        pyautogui.mouseUp(x=x, y=y, button=button)
        time.sleep(0.08)


def move(x: int, y: int, duration: float = 0.0):
    """Move the cursor to a specific location."""
    pyautogui.moveTo(int(x), int(y), duration=float(duration))
    return {"status": "ok", "action": "move", "x": int(x), "y": int(y)}


def scroll(clicks: int = -500, x=None, y=None, method: str = "auto"):
    """Scroll using wheel or PageUp/PageDown fallback."""
    clicks = int(clicks)
    method = str(method or "auto").strip().lower()
    if method not in {"auto", "wheel", "keys"}:
        method = "auto"

    if x is not None and y is not None:
        pyautogui.moveTo(int(x), int(y), duration=0.12)
        time.sleep(0.05)

    if method in {"auto", "keys"}:
        steps = max(1, abs(clicks) // 300)
        key = "pagedown" if clicks < 0 else "pageup"
        for _ in range(steps):
            pyautogui.press(key)
            time.sleep(0.08)
        payload = {"status": "ok", "action": "scroll", "clicks": clicks, "method": "keys", "steps": steps, "key": key}
        if x is not None and y is not None:
            payload["x"] = int(x)
            payload["y"] = int(y)
        return payload

    if x is not None and y is not None:
        pyautogui.scroll(clicks, x=int(x), y=int(y))
        return {"status": "ok", "action": "scroll", "clicks": clicks, "method": "wheel", "x": int(x), "y": int(y)}

    pyautogui.scroll(clicks)
    return {"status": "ok", "action": "scroll", "clicks": clicks, "method": "wheel"}


def click(x: int, y: int, button: str = "left", clicks: int = 1):
    """Click a screen coordinate."""
    perform_click(int(x), int(y), button=str(button), clicks=int(clicks))
    return {"status": "ok", "action": "click", "x": int(x), "y": int(y), "button": str(button), "clicks": int(clicks)}


def double_click(x: int, y: int):
    """Double-click a screen coordinate."""
    perform_click(int(x), int(y), button="left", clicks=2)
    return {"status": "ok", "action": "double_click", "x": int(x), "y": int(y)}


def right_click(x: int, y: int):
    """Right-click a screen coordinate."""
    perform_click(int(x), int(y), button="right", clicks=1)
    return {"status": "ok", "action": "right_click", "x": int(x), "y": int(y)}


def position():
    """Return current cursor position."""
    x, y = pyautogui.position()
    return {"status": "ok", "x": x, "y": y}


__all__ = ["move", "scroll", "perform_click", "click", "double_click", "right_click", "position"]
