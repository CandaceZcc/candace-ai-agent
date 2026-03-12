"""Keyboard and text entry helpers for pc-agent."""

import shutil
import subprocess
import time

import pyautogui


def copy_to_clipboard(text: str) -> bool:
    """Copy text into the desktop clipboard using common Linux clipboard tools."""
    clipboard_commands = [["wl-copy"], ["xclip", "-selection", "clipboard"], ["xsel", "--clipboard", "--input"]]
    for cmd in clipboard_commands:
        if not shutil.which(cmd[0]):
            continue
        try:
            subprocess.run(cmd, input=text, text=True, check=True)
            return True
        except Exception:
            continue
    return False


def type_text_robust(text: str, interval: float = 0.02):
    """Type text with special handling for characters that pyautogui may drop."""
    for ch in text:
        if ch == ".":
            pyautogui.press(".")
        else:
            pyautogui.write(ch, interval=interval)


def paste_or_type_text(text: str, interval: float = 0.02) -> str:
    """Paste text if possible, otherwise fall back to robust typing."""
    if copy_to_clipboard(text):
        pyautogui.hotkey("ctrl", "v")
        return "paste"
    type_text_robust(text, interval=interval)
    return "type"


def input_url(url: str) -> str:
    """Focus the browser address bar and input a URL."""
    pyautogui.hotkey("ctrl", "l")
    time.sleep(0.1)
    pyautogui.hotkey("ctrl", "a")
    pyautogui.press("backspace")
    method = paste_or_type_text(url, interval=0.02)
    pyautogui.press("enter")
    return method


def type_text(text: str, interval: float = 0.03):
    """Type plain text."""
    pyautogui.write(str(text), interval=interval)
    return {"status": "ok", "action": "type", "text": str(text)}


def press_key(key: str, presses: int = 1):
    """Press a keyboard key one or more times."""
    pyautogui.press(str(key), presses=int(presses))
    return {"status": "ok", "action": "press", "key": str(key), "presses": int(presses)}


def hotkey(keys):
    """Press a hotkey chord."""
    if not isinstance(keys, list) or not keys:
        return {"status": "error", "message": "keys must be a non-empty list"}, 400
    pyautogui.hotkey(*keys)
    return {"status": "ok", "action": "hotkey", "keys": keys}


__all__ = ["copy_to_clipboard", "type_text_robust", "paste_or_type_text", "input_url", "type_text", "press_key", "hotkey"]
