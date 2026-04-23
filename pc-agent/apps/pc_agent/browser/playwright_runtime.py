"""Persistent Playwright browser runtime for future automation tasks."""

from __future__ import annotations

import os
import re
import time
from typing import Any, Optional

import numpy as np
import pytesseract
from PIL import Image

from apps.pc_agent.desktop.ocr import extract_targets, match_ocr_text


DEADLINE_KEYWORDS = (
    "due",
    "deadline",
    "ddl",
    "作业",
    "截止",
    "assignment",
    "timeline",
)


class PlaywrightRuntime:
    """Persistent Chromium runtime kept separate from desktop automation."""

    def __init__(self, profile_dir: str, headless: bool = False, screenshot_dir: Optional[str] = None):
        self.profile_dir = os.path.abspath(os.path.expanduser(profile_dir))
        self.headless = headless
        self.screenshot_dir = os.path.abspath(
            os.path.expanduser(screenshot_dir or os.path.join("/tmp", "pc-agent-playwright"))
        )
        self._playwright = None
        self._context = None
        self._page = None

    def _log(self, message: str) -> None:
        """Emit a small runtime log line."""
        print(f"[PLAYWRIGHT] {message}")

    def start(self):
        """Start Playwright lazily with a persistent browser profile."""
        if self._context is not None:
            return self

        try:
            from playwright.sync_api import sync_playwright
        except Exception as e:  # pragma: no cover
            raise RuntimeError(f"Playwright not installed: {e}")

        os.makedirs(self.profile_dir, exist_ok=True)
        os.makedirs(self.screenshot_dir, exist_ok=True)
        self._playwright = sync_playwright().start()
        self._context = self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_dir,
            headless=self.headless,
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._log(f"started profile={self.profile_dir} headless={self.headless}")
        return self

    @property
    def page(self):
        """Return the active page, ensuring the runtime is started."""
        self.start()
        if self._page is None:
            raise RuntimeError("PlaywrightRuntime page is unavailable")
        return self._page

    @property
    def context(self):
        """Return the persistent browser context."""
        self.start()
        if self._context is None:
            raise RuntimeError("PlaywrightRuntime context is unavailable")
        return self._context

    def _ensure_page(self, tab_index: Optional[int] = None):
        """Select the current page or a target tab."""
        pages = self.context.pages
        if not pages:
            self._page = self.context.new_page()
            return self._page
        if tab_index is not None:
            if tab_index < 0 or tab_index >= len(pages):
                raise IndexError(f"tab index out of range: {tab_index}")
            self._page = pages[tab_index]
        elif self._page not in pages:
            self._page = pages[0]
        return self._page

    def _result(self, **payload: Any) -> dict:
        """Return a normalized success payload."""
        return {"status": "ok", **payload}

    def _error(self, action: str, error: Exception) -> dict:
        """Return a normalized error payload."""
        message = str(error)
        self._log(f"{action} error: {message}")
        return {"status": "error", "action": action, "error": message, "error_code": "runtime_error"}

    def health(self) -> dict:
        """Return minimal browser runtime health."""
        started = self._context is not None
        active_url = ""
        tab_count = 0
        if started:
            try:
                page = self._ensure_page()
                active_url = page.url
                tab_count = len(self.context.pages)
            except Exception:
                active_url = ""
                tab_count = 0
        return {
            "started": started,
            "headless": self.headless,
            "active_tab_url": active_url,
            "tab_count": tab_count,
        }

    def _locators_for_text(self, page, target: str):
        """Build a small set of locators for human-facing text."""
        escaped = re.escape(target)
        return [
            page.get_by_role("button", name=re.compile(escaped, re.IGNORECASE)),
            page.get_by_role("link", name=re.compile(escaped, re.IGNORECASE)),
            page.get_by_text(re.compile(escaped, re.IGNORECASE)),
            page.locator(f"text=/{escaped}/i"),
        ]

    def _screenshot_path(self, prefix: str = "shot") -> str:
        filename = f"{prefix}-{int(time.time() * 1000)}.png"
        return os.path.join(self.screenshot_dir, filename)

    def _find_text_dom(self, targets: list[str]) -> dict | None:
        page = self._ensure_page()
        for target in targets:
            if not target:
                continue
            for locator in self._locators_for_text(page, target):
                try:
                    count = locator.count()
                except Exception:
                    continue
                if count <= 0:
                    continue
                try:
                    first = locator.first
                    first.wait_for(timeout=1500)
                    bbox = first.bounding_box() or {}
                    return {
                        "status": "ok",
                        "found": True,
                        "matched_text": target,
                        "strategy": "dom",
                        "selector_hint": "text",
                        "bounds": bbox,
                    }
                except Exception:
                    return {
                        "status": "ok",
                        "found": True,
                        "matched_text": target,
                        "strategy": "dom",
                        "selector_hint": "text",
                    }
        return None

    def _ocr_matches_from_screenshot(self, screenshot_path: str, targets: list[str]) -> list[dict]:
        img = Image.open(screenshot_path)
        ocr_data = pytesseract.image_to_data(np.array(img), lang="chi_sim+eng", output_type=pytesseract.Output.DICT)
        matches: list[dict] = []
        total = len(ocr_data["text"])
        for idx in range(total):
            text = str(ocr_data["text"][idx] or "").strip()
            if not text or not match_ocr_text(targets, text):
                continue
            x = int(ocr_data["left"][idx])
            y = int(ocr_data["top"][idx])
            w = int(ocr_data["width"][idx])
            h = int(ocr_data["height"][idx])
            matches.append(
                {
                    "text": text,
                    "x": x,
                    "y": y,
                    "w": w,
                    "h": h,
                    "center_x": x + w // 2,
                    "center_y": y + h // 2,
                }
            )
        return matches

    def open_url(self, url: str, wait_until: str = "domcontentloaded", new_tab: bool = False) -> dict:
        """Navigate to a URL, optionally in a new tab."""
        try:
            page = self.context.new_page() if new_tab else self._ensure_page()
            self._page = page
            page.goto(url, wait_until=wait_until)
            tabs_info = self.list_tabs()
            self._log(f"open_url {url}")
            return self._result(
                action="open_url",
                url=url,
                page_title=page.title(),
                current_tab=tabs_info.get("current", 0),
            )
        except Exception as e:
            return self._error("open_url", e)

    def click(self, selector: str, timeout: int = 5000) -> dict:
        """Click an element by CSS/text/xpath selector."""
        try:
            page = self._ensure_page()
            page.locator(selector).first.click(timeout=timeout)
            self._log(f"click {selector}")
            return self._result(action="click", selector=selector)
        except Exception as e:
            return self._error("click", e)

    def type_text(self, selector: str, text: str, clear: bool = True, timeout: int = 5000) -> dict:
        """Type text into an element."""
        try:
            page = self._ensure_page()
            locator = page.locator(selector).first
            locator.click(timeout=timeout)
            if clear:
                locator.fill("", timeout=timeout)
            locator.type(text, timeout=timeout)
            self._log(f"type_text {selector}")
            return self._result(action="type_text", selector=selector, text=text)
        except Exception as e:
            return self._error("type_text", e)

    def press_key(self, key: str) -> dict:
        """Press a key on the active page."""
        try:
            page = self._ensure_page()
            page.keyboard.press(key)
            self._log(f"press_key {key}")
            return self._result(action="press_key", key=key)
        except Exception as e:
            return self._error("press_key", e)

    def wait_for_text(self, text: str, timeout: int = 5000) -> dict:
        """Wait until text appears on the page."""
        try:
            page = self._ensure_page()
            page.get_by_text(text).first.wait_for(timeout=timeout)
            self._log(f"wait_for_text {text}")
            return self._result(action="wait_for_text", text=text, timeout=timeout)
        except Exception as e:
            return self._error("wait_for_text", e)

    def get_page_text(self, max_chars: int = 8000) -> dict:
        """Return visible body text."""
        try:
            page = self._ensure_page()
            text = page.locator("body").inner_text(timeout=5000)
            self._log("get_page_text")
            return self._result(action="get_page_text", text=text[:max_chars])
        except Exception as e:
            return self._error("get_page_text", e)

    def ocr(self, max_chars: int = 8000) -> dict:
        """Return page text, falling back to OCR when needed."""
        text_result = self.get_page_text(max_chars=max_chars)
        text = str(text_result.get("text", "")).strip()
        if text_result.get("status") == "ok" and text:
            return self._result(action="ocr", text=text[:max_chars], source="page_text")

        try:
            shot_result = self.screenshot(path=self._screenshot_path("ocr"), full_page=False)
            if shot_result.get("status") != "ok":
                return shot_result
            screenshot_path = str(shot_result["path"])
            text = pytesseract.image_to_string(Image.open(screenshot_path), lang="chi_sim+eng").strip()
            return self._result(action="ocr", text=text[:max_chars], source="ocr_fallback", path=screenshot_path)
        except Exception as e:
            return self._error("ocr", e)

    def find_text(self, data: dict[str, Any]) -> dict:
        """Find text in the current browser page using DOM first, OCR second."""
        try:
            targets = extract_targets(data)
            if not targets:
                return {"status": "error", "action": "find_text", "error_code": "invalid_request", "message": "text or texts is required"}

            dom_result = self._find_text_dom(targets)
            if dom_result is not None:
                return {"action": "find_text", **dom_result}

            shot_result = self.screenshot(path=self._screenshot_path("find-text"), full_page=False)
            if shot_result.get("status") != "ok":
                return shot_result
            matches = self._ocr_matches_from_screenshot(str(shot_result["path"]), targets)
            if matches:
                first = matches[0]
                return self._result(
                    action="find_text",
                    found=True,
                    matched_text=first["text"],
                    strategy="ocr",
                    count=len(matches),
                    matches=matches,
                )
            return {
                "status": "not_found",
                "action": "find_text",
                "found": False,
                "targets": targets,
                "strategy": "ocr",
                "error_code": "text_not_found",
            }
        except Exception as e:
            return self._error("find_text", e)

    def click_text(self, data: dict[str, Any]) -> dict:
        """Click text in the current browser page using DOM first, OCR second."""
        try:
            targets = extract_targets(data)
            if not targets:
                return {"status": "error", "action": "click_text", "error_code": "invalid_request", "message": "text or texts is required"}

            page = self._ensure_page()
            for target in targets:
                for locator in self._locators_for_text(page, target):
                    try:
                        if locator.count() <= 0:
                            continue
                        locator.first.click(timeout=2000)
                        return self._result(
                            action="click_text",
                            matched_text=target,
                            strategy="dom",
                        )
                    except Exception:
                        continue

            shot_result = self.screenshot(path=self._screenshot_path("click-text"), full_page=False)
            if shot_result.get("status") != "ok":
                return shot_result
            matches = self._ocr_matches_from_screenshot(str(shot_result["path"]), targets)
            if matches:
                first = matches[0]
                page.mouse.click(first["center_x"], first["center_y"])
                return self._result(
                    action="click_text",
                    matched_text=first["text"],
                    strategy="ocr",
                    center_x=first["center_x"],
                    center_y=first["center_y"],
                )
            return {
                "status": "not_found",
                "action": "click_text",
                "targets": targets,
                "strategy": "ocr",
                "error_code": "text_not_found",
            }
        except Exception as e:
            return self._error("click_text", e)

    def extract_deadline(self, max_chars: int = 12000) -> dict:
        """Extract visible deadline-like lines from the current page."""
        try:
            page = self._ensure_page()
            text_result = self.ocr(max_chars=max_chars)
            if text_result.get("status") != "ok":
                return text_result
            text = str(text_result.get("text", "") or "")
            page_title = page.title()
            lines = [line.strip() for line in text.splitlines() if line.strip()]
            items = []
            for line in lines:
                lower = line.lower()
                for keyword in DEADLINE_KEYWORDS:
                    if keyword in lower or keyword in line:
                        items.append(
                            {
                                "text": line,
                                "matched_keyword": keyword,
                                "page_title": page_title,
                                "source": text_result.get("source", "page_text"),
                            }
                        )
                        break
            return self._result(action="extract_deadline", items=items, count=len(items), page_title=page_title)
        except Exception as e:
            return self._error("extract_deadline", e)

    def screenshot(self, path: Optional[str] = None, full_page: bool = True) -> dict:
        """Save a screenshot and return its path."""
        try:
            page = self._ensure_page()
            if path is None:
                path = self._screenshot_path()
            page.screenshot(path=path, full_page=full_page)
            self._log(f"screenshot {path}")
            return self._result(action="screenshot", path=path)
        except Exception as e:
            return self._error("screenshot", e)

    def list_tabs(self) -> dict:
        """List open tabs in the persistent browser context."""
        try:
            pages = self.context.pages
            current_index = pages.index(self._ensure_page()) if pages else 0
            tabs = []
            for index, page in enumerate(pages):
                tabs.append(
                    {
                        "index": index,
                        "url": page.url,
                        "title": page.title(),
                        "active": index == current_index,
                    }
                )
            return self._result(action="list_tabs", current=current_index, tabs=tabs)
        except Exception as e:
            return self._error("list_tabs", e)

    def switch_tab(self, index: int) -> dict:
        """Switch the active page to an existing tab index."""
        try:
            page = self._ensure_page(tab_index=index)
            page.bring_to_front()
            self._log(f"switch_tab {index}")
            return self._result(action="switch_tab", index=index, url=page.url, title=page.title())
        except Exception as e:
            return self._error("switch_tab", e)

    def close(self):
        """Close browser resources."""
        if self._page is not None:
            self._page = None
        if self._context is not None:
            self._context.close()
            self._context = None
        if self._playwright is not None:
            self._playwright.stop()
            self._playwright = None
        self._log("closed")


def demo_open_url(url: str = "https://example.com") -> dict:
    """Simple demo entrypoint for manual testing."""
    runtime = PlaywrightRuntime(profile_dir=os.path.expanduser("~/.cache/pc-agent/playwright-profile"))
    try:
        runtime.start()
        result = runtime.open_url(url)
        if result.get("status") != "ok":
            return result
        return runtime.get_page_text(max_chars=500)
    finally:
        runtime.close()


if __name__ == "__main__":
    print(demo_open_url())
