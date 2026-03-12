"""OCR helpers for pc-agent."""

import re

import numpy as np
import pyautogui
import pytesseract

from apps.pc_agent.desktop.mouse import perform_click


def normalize_match_text(text: str) -> str:
    """Normalize OCR text for fuzzy comparisons."""
    return re.sub(r"[\s\W_]+", "", (text or "").strip().lower())


def extract_targets(data) -> list[str]:
    """Extract target texts from request JSON."""
    if "texts" in data and isinstance(data["texts"], list):
        return [str(item).strip() for item in data["texts"] if str(item).strip()]
    target = str(data.get("text", "")).strip()
    return [target] if target else []


def match_ocr_text(candidates: list[str], detected_text: str) -> bool:
    """Match OCR output against one or more candidates."""
    detected_norm = normalize_match_text(detected_text)
    if not detected_norm:
        return False
    for candidate in candidates:
        candidate_norm = normalize_match_text(candidate)
        if not candidate_norm:
            continue
        if candidate_norm in detected_norm or detected_norm in candidate_norm:
            return True
    return False


def find_text(data):
    """Locate OCR matches on the current screen."""
    targets = extract_targets(data)
    if not targets:
        return {"status": "error", "message": "text or texts is required"}, 400
    lang = str(data.get("lang", "chi_sim+eng"))
    img = pyautogui.screenshot()
    img_np = np.array(img)
    ocr_data = pytesseract.image_to_data(img_np, lang=lang, output_type=pytesseract.Output.DICT)
    matches = []
    n = len(ocr_data["text"])
    for i in range(n):
        text = ocr_data["text"][i].strip()
        if not text:
            continue
        if match_ocr_text(targets, text):
            x = int(ocr_data["left"][i]); y = int(ocr_data["top"][i]); w = int(ocr_data["width"][i]); h = int(ocr_data["height"][i])
            matches.append({"text": text, "x": x, "y": y, "w": w, "h": h, "center_x": x + w // 2, "center_y": y + h // 2})
    if not matches:
        return {"status": "not_found", "targets": targets, "matches": []}, 404
    return {"status": "ok", "targets": targets, "count": len(matches), "matches": matches}


def click_text(data):
    """Click the first OCR text match on screen."""
    targets = extract_targets(data)
    if not targets:
        return {"status": "error", "message": "text or texts is required"}, 400
    lang = str(data.get("lang", "chi_sim+eng"))
    img = pyautogui.screenshot()
    img_np = np.array(img)
    ocr_data = pytesseract.image_to_data(img_np, lang=lang, output_type=pytesseract.Output.DICT)
    n = len(ocr_data["text"])
    for i in range(n):
        text = ocr_data["text"][i].strip()
        if not text:
            continue
        if match_ocr_text(targets, text):
            x = int(ocr_data["left"][i]); y = int(ocr_data["top"][i]); w = int(ocr_data["width"][i]); h = int(ocr_data["height"][i])
            cx = x + w // 2; cy = y + h // 2
            perform_click(cx, cy, button="left", clicks=1)
            return {"status": "ok", "targets": targets, "matched_text": text, "x": x, "y": y, "w": w, "h": h, "center_x": cx, "center_y": cy, "click_method": "mouse_down_up"}
    return {"status": "not_found", "targets": targets}, 404


__all__ = ["normalize_match_text", "extract_targets", "match_ocr_text", "find_text", "click_text"]
