"""Compatibility entrypoint for the QQ AI bridge."""

from apps.qq_ai_bridge import runtime
from apps.qq_ai_bridge.app import app


if __name__ == "__main__":
    print("[SYSTEM] bridge 启动中，监听 0.0.0.0:5000")
    print(f"[SYSTEM] 私聊文件目录: {runtime.PRIVATE_UPLOAD_DIR}")
    print(f"[SYSTEM] 群聊文件目录: {runtime.GROUP_UPLOAD_DIR}")
    app.run(host="0.0.0.0", port=5000)
