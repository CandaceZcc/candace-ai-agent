"""Runtime disk maintenance, rotating logs, and process metrics."""

from __future__ import annotations

import logging
import threading
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any


class TeeStream:
    """Mirror a text stream to one rotating sink without flushing partial writes."""

    def __init__(self, original: Any, log_sink: "RotatingLogSink", stream_name: str) -> None:
        self._original = original
        self._log_sink = log_sink
        self._stream_name = stream_name
        self._lock = threading.Lock()

    def write(self, data: str) -> int:
        with self._lock:
            self._original.write(data)
            self._log_sink.write(data, stream_name=self._stream_name)
            if "\n" in str(data or ""):
                self._original.flush()
        return len(data)

    def flush(self) -> None:
        self._original.flush()
        self._log_sink.flush(stream_name=self._stream_name)

    def isatty(self) -> bool:
        return bool(getattr(self._original, "isatty", lambda: False)())


class RotatingLogSink:
    """One rotating file writer shared by stdout and stderr tee streams."""

    def __init__(self, path: str | Path, *, max_bytes: int, backup_count: int) -> None:
        self.path = Path(path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._buffers: dict[str, str] = {}
        self._logger = logging.Logger(f"candace.bridge.{id(self)}", level=logging.INFO)
        self._logger.propagate = False
        self._handler = RotatingFileHandler(
            self.path,
            maxBytes=max(1, int(max_bytes)),
            backupCount=max(1, int(backup_count)),
            encoding="utf-8",
        )
        self._handler.setFormatter(logging.Formatter("%(message)s"))
        self._logger.addHandler(self._handler)

    def write(self, data: str, *, stream_name: str = "stdout") -> int:
        text = str(data or "")
        if not text:
            return 0
        with self._lock:
            buffered = self._buffers.get(stream_name, "") + text
            while "\n" in buffered:
                line, buffered = buffered.split("\n", 1)
                self._logger.info(line.rstrip("\r"))
            self._buffers[stream_name] = buffered
        return len(text)

    def flush(self, *, stream_name: str | None = None) -> None:
        with self._lock:
            names = [stream_name] if stream_name is not None else list(self._buffers)
            for name in names:
                buffered = self._buffers.get(name, "")
                if buffered:
                    self._logger.info(buffered.rstrip("\r"))
                    self._buffers[name] = ""
            self._handler.flush()

    def close(self) -> None:
        with self._lock:
            self.flush()
            self._logger.removeHandler(self._handler)
            self._handler.close()


def _iter_files(root: Path) -> list[tuple[Path, int, float]]:
    files: list[tuple[Path, int, float]] = []
    if not root.exists():
        return files
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        files.append((path, int(stat.st_size), float(stat.st_mtime)))
    return files


def get_directory_status(root: str | Path) -> dict[str, Any]:
    resolved = Path(root).expanduser().resolve()
    files = _iter_files(resolved)
    return {
        "path": str(resolved),
        "file_count": len(files),
        "total_bytes": sum(size for _path, size, _mtime in files),
    }


def cleanup_temp_directory(
    root: str | Path,
    *,
    max_age_seconds: int,
    max_total_bytes: int,
    now: float | None = None,
) -> dict[str, Any]:
    resolved = Path(root).expanduser().resolve()
    resolved.mkdir(parents=True, exist_ok=True)
    current = time.time() if now is None else float(now)
    removed_files = 0
    removed_bytes = 0

    files = _iter_files(resolved)
    survivors: list[tuple[Path, int, float]] = []
    for path, size, modified_at in files:
        if max_age_seconds > 0 and current - modified_at > max_age_seconds:
            try:
                path.unlink()
            except OSError:
                survivors.append((path, size, modified_at))
            else:
                removed_files += 1
                removed_bytes += size
            continue
        survivors.append((path, size, modified_at))

    total_bytes = sum(size for _path, size, _mtime in survivors)
    if max_total_bytes > 0 and total_bytes > max_total_bytes:
        for path, size, _modified_at in sorted(survivors, key=lambda item: item[2]):
            if total_bytes <= max_total_bytes:
                break
            try:
                path.unlink()
            except OSError:
                continue
            removed_files += 1
            removed_bytes += size
            total_bytes -= size

    status = get_directory_status(resolved)
    return {
        **status,
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
    }


def cleanup_log_backups(
    log_path: str | Path,
    *,
    max_age_seconds: int,
    max_total_bytes: int,
    now: float | None = None,
) -> dict[str, int | str]:
    current_log = Path(log_path).expanduser().resolve()
    current = time.time() if now is None else float(now)
    backups: list[tuple[Path, int, float]] = []
    for path in current_log.parent.glob(f"{current_log.name}.*"):
        if not path.is_file():
            continue
        try:
            stat = path.stat()
        except OSError:
            continue
        backups.append((path, int(stat.st_size), float(stat.st_mtime)))

    removed_files = 0
    removed_bytes = 0
    survivors: list[tuple[Path, int, float]] = []
    for path, size, modified_at in backups:
        if max_age_seconds > 0 and current - modified_at > max_age_seconds:
            try:
                path.unlink()
            except OSError:
                survivors.append((path, size, modified_at))
            else:
                removed_files += 1
                removed_bytes += size
            continue
        survivors.append((path, size, modified_at))

    total_bytes = sum(size for _path, size, _mtime in survivors)
    if max_total_bytes > 0 and total_bytes > max_total_bytes:
        for path, size, _modified_at in sorted(survivors, key=lambda item: item[2]):
            if total_bytes <= max_total_bytes:
                break
            try:
                path.unlink()
            except OSError:
                continue
            removed_files += 1
            removed_bytes += size
            total_bytes -= size

    remaining = _iter_files(current_log.parent)
    remaining_backups = [item for item in remaining if item[0].name.startswith(f"{current_log.name}.")]
    return {
        "path": str(current_log),
        "removed_files": removed_files,
        "removed_bytes": removed_bytes,
        "backup_files": len(remaining_backups),
        "backup_bytes": sum(size for _path, size, _mtime in remaining_backups),
    }


def get_process_rss_bytes() -> int:
    status_path = Path("/proc/self/status")
    try:
        for line in status_path.read_text(encoding="utf-8", errors="ignore").splitlines():
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return 0
    return 0


__all__ = [
    "RotatingLogSink",
    "TeeStream",
    "cleanup_log_backups",
    "cleanup_temp_directory",
    "get_directory_status",
    "get_process_rss_bytes",
]
