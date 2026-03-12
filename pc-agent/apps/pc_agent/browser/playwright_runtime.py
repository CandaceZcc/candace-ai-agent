"""Persistent Playwright browser runtime for future automation tasks."""

from __future__ import annotations

import os
import time
from typing import Any, Optional


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
        return {"status": "error", "action": action, "error": message}

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

    def screenshot(self, path: Optional[str] = None, full_page: bool = True) -> dict:
        """Save a screenshot and return its path."""
        try:
            page = self._ensure_page()
            if path is None:
                filename = f"shot-{int(time.time())}.png"
                path = os.path.join(self.screenshot_dir, filename)
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
