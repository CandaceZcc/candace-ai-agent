"""Chrome launcher helpers."""

import subprocess


def launch_browser_url(url: str, new_window: bool = True) -> str:
    """Launch Google Chrome directly to a URL."""
    cmd = ["google-chrome"]
    if new_window:
        cmd.append("--new-window")
    cmd.append(url)
    subprocess.Popen(cmd)
    return "chrome-direct"


def open_url(url: str):
    """Open a URL in the current Chrome session."""
    input_method = launch_browser_url(str(url).strip(), new_window=False)
    return {"status": "ok", "action": "open_url", "url": str(url).strip(), "input_method": input_method}


def launch_chrome():
    """Launch a blank Chrome window."""
    subprocess.Popen(["google-chrome"])
    return {"status": "ok", "action": "launch_chrome"}


def launch_and_open(url: str):
    """Launch a new Chrome window and open a URL."""
    input_method = launch_browser_url(str(url).strip(), new_window=True)
    return {"status": "ok", "action": "launch_and_open", "url": str(url).strip(), "input_method": input_method}


__all__ = ["launch_browser_url", "launch_chrome", "open_url", "launch_and_open"]
