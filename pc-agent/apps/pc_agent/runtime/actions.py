"""Compatibility exports for pc-agent actions."""

from apps.pc_agent.browser.chrome import launch_and_open, launch_chrome, open_url
from apps.pc_agent.desktop.keyboard import hotkey, paste_or_type_text, press_key as press, type_text
from apps.pc_agent.desktop.mouse import click, double_click, move, perform_click, position, right_click, scroll
from apps.pc_agent.desktop.ocr import click_text, find_text
from apps.pc_agent.desktop.screen import ocr_screen, screen_size, screenshot

__all__ = [
    "move",
    "scroll",
    "click",
    "double_click",
    "right_click",
    "type_text",
    "press",
    "hotkey",
    "position",
    "screen_size",
    "screenshot",
    "open_url",
    "ocr_screen",
    "find_text",
    "click_text",
    "launch_chrome",
    "launch_and_open",
    "paste_or_type_text",
    "perform_click",
]
