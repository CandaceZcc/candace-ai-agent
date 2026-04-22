"""Compatibility entrypoint for the QQ AI bridge."""

import os

from apps.qq_ai_bridge import runtime
from apps.qq_ai_bridge.app import app


def _serve() -> None:
    """Serve Flask without Werkzeug startup quirks (sandbox / restricted raw sockets)."""
    host = os.getenv("BRIDGE_HOST", "0.0.0.0").strip() or "0.0.0.0"
    port = max(1, int(os.getenv("BRIDGE_PORT", "5000")))
    threads = max(1, int(os.getenv("WAITRESS_THREADS", "8")))
    print(f"[SYSTEM] bridge 启动中，监听 {host}:{port}")
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
