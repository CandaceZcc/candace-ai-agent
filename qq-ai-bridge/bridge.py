"""Compatibility entrypoint for the QQ AI bridge."""

import os
import sys
import threading
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


class _TeeStream:
    """Mirror process output to terminal and bridge.log."""

    def __init__(self, original, log_file):
        self._original = original
        self._log_file = log_file
        self._lock = threading.Lock()

    def write(self, data):
        with self._lock:
            self._original.write(data)
            self._log_file.write(data)
            self.flush()
        return len(data)

    def flush(self):
        self._original.flush()
        self._log_file.flush()

    def isatty(self):
        return bool(getattr(self._original, "isatty", lambda: False)())


def _install_bridge_log_tee() -> Path:
    log_path = (REPO_ROOT / ".runtime" / "logs" / "bridge.log").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_file = log_path.open("a", encoding="utf-8", buffering=1)
    sys.stdout = _TeeStream(sys.stdout, log_file)
    sys.stderr = _TeeStream(sys.stderr, log_file)
    return log_path


_BRIDGE_LOG_PATH = _install_bridge_log_tee()

from apps.qq_ai_bridge import runtime
from apps.qq_ai_bridge.app import app


def _serve() -> None:
    """Serve Flask without Werkzeug startup quirks (sandbox / restricted raw sockets)."""
    host = os.getenv("BRIDGE_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = max(1, int(os.getenv("BRIDGE_PORT", "5000")))
    threads = max(1, int(os.getenv("WAITRESS_THREADS", "8")))
    print(f"[SYSTEM] bridge 启动中，监听 {host}:{port}")
    print(f"[SYSTEM] bridge 日志文件: {_BRIDGE_LOG_PATH}")
    print(f"[SYSTEM] 私聊文件目录: {runtime.PRIVATE_UPLOAD_DIR}")
    print(f"[SYSTEM] 群聊文件目录: {runtime.GROUP_UPLOAD_DIR}")
    print("[SYSTEM] 已启用 VoCat webhook: /vocat/webhook")
    print("[SYSTEM] 已启用 VoCat 遥控命令: #表情 <id>, #说 <text>")
    try:
        from waitress import serve

        print("[SYSTEM] 使用 Waitress（生产级 WSGI），避免 Flask 开发服务器 socket 权限问题")
        serve(app, host=host, port=port, threads=threads)
    except ImportError:
        print("[SYSTEM] waitress 未安装，回退 Flask 内置服务器（pip install waitress 推荐）")
        app.run(host=host, port=port, threaded=True, use_reloader=False)


if __name__ == "__main__":
    _serve()
