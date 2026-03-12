"""Screen capture and OCR surface helpers."""

import time

import cv2
import numpy as np
import pyautogui
import pytesseract


def screen_size():
    """Return current screen dimensions."""
    width, height = pyautogui.size()
    return {"status": "ok", "width": width, "height": height}


def screenshot():
    """Capture a screenshot to a temp file."""
    ts = int(time.time())
    path = f"/tmp/pc-agent-screen-{ts}.png"
    img = pyautogui.screenshot()
    img.save(path)
    return {"status": "ok", "saved_to": path}


def ocr_screen():
    """OCR the current screen and return recognized text."""
    img = pyautogui.screenshot()
    img_np = np.array(img)
    gray = cv2.cvtColor(img_np, cv2.COLOR_BGR2GRAY)
    text = pytesseract.image_to_string(gray)
    return {"status": "ok", "text": text}


__all__ = ["screen_size", "screenshot", "ocr_screen"]
