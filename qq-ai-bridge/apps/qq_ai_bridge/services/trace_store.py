"""Small in-memory trace store for bridge request observability."""

from __future__ import annotations

import threading
import time
import uuid
from collections import OrderedDict
from datetime import datetime, timezone
from typing import Any

MAX_TRACES = 200

_TRACE_LOCK = threading.Lock()
_TRACES: OrderedDict[str, dict[str, Any]] = OrderedDict()


def new_trace_id(payload: dict[str, Any] | None = None) -> str:
    payload = payload or {}
    candidate = payload.get("tool_call_id")
    nested = payload.get("payload")
    if not candidate and isinstance(nested, dict):
        candidate = nested.get("tool_call_id")
    cleaned = str(candidate or "").strip()
    return cleaned or uuid.uuid4().hex[:8]


def trace_prefix(trace_id: str | None) -> str:
    return f"[TRACE {trace_id or '-'}]"


def start_trace(trace_id: str, *, source: str = "", input_text: str = "") -> dict[str, Any]:
    now = time.monotonic()
    item = {
        "trace_id": trace_id,
        "start_time": datetime.now(timezone.utc).isoformat(),
        "_started_at": now,
        "source": str(source or ""),
        "input": str(input_text or ""),
        "steps": [],
        "result": None,
        "status": "running",
        "duration_ms": 0,
    }
    with _TRACE_LOCK:
        _TRACES[trace_id] = item
        _TRACES.move_to_end(trace_id)
        while len(_TRACES) > MAX_TRACES:
            _TRACES.popitem(last=False)
        return _public_trace(item)


def add_trace_step(trace_id: str | None, stage: str, **fields: Any) -> None:
    if not trace_id:
        return
    step = {"stage": stage, **{k: v for k, v in fields.items() if v is not None}}
    with _TRACE_LOCK:
        item = _TRACES.get(trace_id)
        if not item:
            item = {
                "trace_id": trace_id,
                "start_time": datetime.now(timezone.utc).isoformat(),
                "_started_at": time.monotonic(),
                "source": "",
                "input": "",
                "steps": [],
                "result": None,
                "status": "running",
                "duration_ms": 0,
            }
            _TRACES[trace_id] = item
            _TRACES.move_to_end(trace_id)
            while len(_TRACES) > MAX_TRACES:
                _TRACES.popitem(last=False)
        item["steps"].append(step)


def finish_trace(trace_id: str | None, *, result: Any = None, status: str = "ok", source: str | None = None) -> None:
    if not trace_id:
        return
    with _TRACE_LOCK:
        item = _TRACES.get(trace_id)
        if not item:
            return
        if source is not None:
            item["source"] = str(source or "")
        item["result"] = result
        item["status"] = str(status or "ok")
        item["duration_ms"] = int((time.monotonic() - float(item.get("_started_at") or time.monotonic())) * 1000)


def list_traces() -> list[dict[str, Any]]:
    with _TRACE_LOCK:
        return [_summary_trace(item) for item in reversed(_TRACES.values())]


def get_trace(trace_id: str) -> dict[str, Any] | None:
    with _TRACE_LOCK:
        item = _TRACES.get(str(trace_id or ""))
        return _public_trace(item) if item else None


def _summary_trace(item: dict[str, Any]) -> dict[str, Any]:
    public = _public_trace(item)
    public.pop("steps", None)
    public.pop("result", None)
    return public


def _public_trace(item: dict[str, Any]) -> dict[str, Any]:
    public = {k: v for k, v in item.items() if not k.startswith("_")}
    public["duration"] = public.get("duration_ms", 0)
    return public
