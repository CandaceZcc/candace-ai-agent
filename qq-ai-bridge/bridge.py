"""Compatibility entrypoint for the QQ AI bridge."""

import os
import sys
from pathlib import Path

from apps.qq_ai_bridge.services.runtime_maintenance import (
    RotatingLogSink,
    TeeStream,
    cleanup_log_backups,
    cleanup_temp_directory,
)

REPO_ROOT = Path(__file__).resolve().parent.parent


def _install_bridge_log_tee() -> tuple[Path, RotatingLogSink, dict]:
    log_path = (REPO_ROOT / ".runtime" / "logs" / "bridge.log").resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    max_bytes = max(1024 * 1024, int(os.getenv("BRIDGE_LOG_MAX_BYTES", str(20 * 1024 * 1024))))
    backup_count = max(1, int(os.getenv("BRIDGE_LOG_BACKUP_COUNT", "7")))
    backup_cleanup = cleanup_log_backups(
        log_path,
        max_age_seconds=max(24 * 3600, int(os.getenv("BRIDGE_LOG_BACKUP_MAX_AGE_SECONDS", str(14 * 24 * 3600)))),
        max_total_bytes=max(max_bytes, int(os.getenv("BRIDGE_LOG_BACKUP_MAX_BYTES", str(max_bytes * backup_count)))),
    )
    log_sink = RotatingLogSink(log_path, max_bytes=max_bytes, backup_count=backup_count)
    sys.stdout = TeeStream(sys.stdout, log_sink, "stdout")
    sys.stderr = TeeStream(sys.stderr, log_sink, "stderr")
    return log_path, log_sink, backup_cleanup


_BRIDGE_LOG_PATH, _BRIDGE_LOG_SINK, _BRIDGE_BACKUP_CLEANUP = _install_bridge_log_tee()
print(
    "[SYSTEM] 历史日志清理"
    f" removed_files={_BRIDGE_BACKUP_CLEANUP['removed_files']}"
    f" removed_bytes={_BRIDGE_BACKUP_CLEANUP['removed_bytes']}"
    f" backup_files={_BRIDGE_BACKUP_CLEANUP['backup_files']}"
    f" backup_bytes={_BRIDGE_BACKUP_CLEANUP['backup_bytes']}"
)

from apps.qq_ai_bridge import runtime
from apps.qq_ai_bridge.app import app

_TEMP_CLEANUP = cleanup_temp_directory(
    runtime.IMAGE_TMP_DIR,
    max_age_seconds=max(3600, int(os.getenv("IMAGE_TMP_MAX_AGE_SECONDS", str(3 * 24 * 3600)))),
    max_total_bytes=max(10 * 1024 * 1024, int(os.getenv("IMAGE_TMP_MAX_BYTES", str(512 * 1024 * 1024)))),
)
print(
    "[SYSTEM] 临时图片清理"
    f" removed_files={_TEMP_CLEANUP['removed_files']}"
    f" removed_bytes={_TEMP_CLEANUP['removed_bytes']}"
    f" remaining_files={_TEMP_CLEANUP['file_count']}"
    f" remaining_bytes={_TEMP_CLEANUP['total_bytes']}"
)


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
