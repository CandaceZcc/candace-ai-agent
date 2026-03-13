"""Persistent JSON stores for reminders and scheduler state."""

from __future__ import annotations

import json
import os
import threading
import traceback
from datetime import datetime
from typing import Any, Callable

from apps.qq_ai_bridge.services.time_utils import get_now_local


_LOCK_REGISTRY: dict[str, threading.Lock] = {}
_LOCK_REGISTRY_GUARD = threading.Lock()
DONE_LIMIT = 50


def _get_path_lock(path: str) -> threading.Lock:
    with _LOCK_REGISTRY_GUARD:
        lock = _LOCK_REGISTRY.get(path)
        if lock is None:
            lock = threading.Lock()
            _LOCK_REGISTRY[path] = lock
        return lock


class JsonFileStore:
    """Thread-safe JSON file store with atomic writes."""

    def __init__(self, path: str, default_factory):
        self.path = path
        self.default_factory = default_factory
        self.lock = _get_path_lock(path)
        self._ensure_file()

    def _ensure_file(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        if os.path.exists(self.path):
            return
        self._write_data(self.default_factory())

    def _write_data(self, payload: dict[str, Any]) -> None:
        tmp_path = f"{self.path}.tmp"
        with open(tmp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp_path, self.path)

    def _load_unlocked(self) -> dict[str, Any]:
        self._ensure_file()
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            print(f"[STORE] failed load path={self.path}")
            traceback.print_exc()
            payload = self.default_factory()
            self._write_data(payload)
            return payload

    def load(self) -> dict[str, Any]:
        with self.lock:
            return self._load_unlocked()

    def save(self, payload: dict[str, Any]) -> None:
        with self.lock:
            try:
                self._write_data(payload)
            except Exception:
                print(f"[STORE] failed save path={self.path}")
                traceback.print_exc()
                raise

    def mutate(self, mutator: Callable[[dict[str, Any]], Any]) -> Any:
        with self.lock:
            payload = self._load_unlocked()
            result = mutator(payload)
            self._write_data(payload)
            return result


class ReminderStore:
    """Manage persisted reminder items."""

    def __init__(self, path: str):
        self.store = JsonFileStore(path, self._default_payload)

    @staticmethod
    def _default_payload() -> dict[str, Any]:
        return {"next_id": 1, "items": []}

    def load_all(self) -> dict[str, Any]:
        payload = self.store.load()
        payload = self._normalize_payload(payload)
        items = payload.get("items", [])
        pending_count = sum(1 for item in items if item.get("status") == "pending")
        done_count = sum(1 for item in items if item.get("status") == "done")
        cancelled_count = sum(1 for item in items if item.get("status") == "cancelled")
        print(
            f"[STORE] loaded reminders count={len(items)}"
            f" pending={pending_count}"
            f" done={done_count}"
            f" cancelled={cancelled_count}"
        )
        return payload

    def save_all(self, payload: dict[str, Any]) -> None:
        normalized = self._normalize_payload(payload)
        items = normalized.get("items", [])
        self.store.save(normalized)
        pending_count = sum(1 for item in items if item.get("status") == "pending")
        done_count = sum(1 for item in items if item.get("status") == "done")
        cancelled_count = sum(1 for item in items if item.get("status") == "cancelled")
        print(
            f"[STORE] saved reminders count={len(items)}"
            f" pending={pending_count}"
            f" done={done_count}"
            f" cancelled={cancelled_count}"
        )

    def add_reminder(self, user_id: int, trigger_at: datetime, text: str, is_recurring: bool = False) -> dict[str, Any]:
        def mutate(payload: dict[str, Any]) -> dict[str, Any]:
            normalized = self._normalize_payload(payload)
            reminder_id = int(normalized.get("next_id", 1))
            item = {
                "id": reminder_id,
                "user_id": int(user_id),
                "text": text,
                "trigger_at": trigger_at.isoformat(),
                "status": "pending",
                "created_at": get_now_local().isoformat(),
                "fired_at": None,
                "cancelled_at": None,
                "is_recurring": bool(is_recurring),
            }
            normalized["next_id"] = reminder_id + 1
            normalized.setdefault("items", []).append(item)
            payload.clear()
            payload.update(normalized)
            return item

        item = self.store.mutate(mutate)
        self.load_all()
        print(f"[REMINDER] added id={item['id']} trigger_at={item['trigger_at']} text={item['text']}")
        return item

    def list_pending(self, user_id: int | None = None) -> list[dict[str, Any]]:
        items = self.load_all().get("items", [])
        pending = [item for item in items if item.get("status") == "pending"]
        if user_id is not None:
            pending = [item for item in pending if int(item.get("user_id", 0)) == int(user_id)]
        return sorted(pending, key=lambda item: item.get("trigger_at", ""))

    def list_done(self, user_id: int | None = None, limit: int = 5) -> list[dict[str, Any]]:
        items = self.load_all().get("items", [])
        done = [item for item in items if item.get("status") == "done"]
        if user_id is not None:
            done = [item for item in done if int(item.get("user_id", 0)) == int(user_id)]
        done.sort(key=lambda item: item.get("fired_at") or item.get("trigger_at", ""), reverse=True)
        return done[:limit]

    def get_next_pending(self, user_id: int | None = None) -> dict[str, Any] | None:
        pending = self.list_pending(user_id=user_id)
        if pending:
            print(f"[REMINDER] next_pending id={pending[0].get('id')}")
            return pending[0]
        print("[REMINDER] next_pending id=None")
        return None

    def cancel_reminder(self, reminder_id: int, user_id: int | None = None) -> dict[str, Any] | None:
        cancelled = self._update_status(
            reminder_id=reminder_id,
            new_status="cancelled",
            user_id=user_id,
            timestamp_field="cancelled_at",
            timestamp=get_now_local(),
        )
        if cancelled:
            print(f"[REMINDER] deleted id={cancelled['id']}")
        return cancelled

    def clear_pending(self, user_id: int | None = None) -> int:
        now = get_now_local().isoformat()

        def mutate(payload: dict[str, Any]) -> int:
            normalized = self._normalize_payload(payload)
            count = 0
            for item in normalized.get("items", []):
                same_user = user_id is None or int(item.get("user_id", 0)) == int(user_id)
                if same_user and item.get("status") == "pending":
                    item["status"] = "cancelled"
                    item["cancelled_at"] = now
                    count += 1
            payload.clear()
            payload.update(self._prune_done_items(normalized))
            return count

        count = self.store.mutate(mutate)
        self.load_all()
        print(f"[REMINDER] cleared count={count} user_id={user_id}")
        return count

    def mark_fired(self, reminder_id: int, fired_at: datetime) -> dict[str, Any] | None:
        updated = self._update_status(
            reminder_id=reminder_id,
            new_status="done",
            user_id=None,
            timestamp_field="fired_at",
            timestamp=fired_at,
        )
        if updated:
            print(f"[REMINDER] completed id={updated['id']} fired_at={updated.get('fired_at')}")
        return updated

    def _update_status(
        self,
        reminder_id: int,
        new_status: str,
        user_id: int | None,
        timestamp_field: str,
        timestamp: datetime,
    ) -> dict[str, Any] | None:
        timestamp_value = timestamp.isoformat()

        def mutate(payload: dict[str, Any]) -> dict[str, Any] | None:
            normalized = self._normalize_payload(payload)
            target = None
            for item in normalized.get("items", []):
                if int(item.get("id", 0)) != int(reminder_id):
                    continue
                if user_id is not None and int(item.get("user_id", 0)) != int(user_id):
                    continue
                if item.get("status") != "pending" and new_status in {"done", "cancelled"}:
                    target = None
                    break
                item["status"] = new_status
                item[timestamp_field] = timestamp_value
                target = dict(item)
                break
            payload.clear()
            payload.update(self._prune_done_items(normalized))
            return target

        return self.store.mutate(mutate)

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = {"next_id": int(payload.get("next_id", 1) or 1), "items": []}
        for item in payload.get("items", []):
            if not isinstance(item, dict):
                continue
            status = str(item.get("status") or "").strip()
            if not status:
                if item.get("completed"):
                    status = "done"
                else:
                    status = "pending"
            normalized_item = {
                "id": int(item.get("id", 0) or 0),
                "user_id": int(item.get("user_id", 0) or 0),
                "text": str(item.get("text", "")).strip(),
                "trigger_at": str(item.get("trigger_at", "")),
                "status": status,
                "created_at": item.get("created_at") or get_now_local().isoformat(),
                "fired_at": item.get("fired_at") or item.get("completed_at") or item.get("last_sent_at"),
                "cancelled_at": item.get("cancelled_at"),
                "is_recurring": bool(item.get("is_recurring", False)),
            }
            if normalized_item["id"] <= 0 or not normalized_item["text"] or not normalized_item["trigger_at"]:
                continue
            normalized["items"].append(normalized_item)
            normalized["next_id"] = max(normalized["next_id"], normalized_item["id"] + 1)
        return self._prune_done_items(normalized)

    def _prune_done_items(self, payload: dict[str, Any]) -> dict[str, Any]:
        done_items = [item for item in payload.get("items", []) if item.get("status") == "done"]
        keep_done_ids = {
            item["id"]
            for item in sorted(done_items, key=lambda item: item.get("fired_at") or item.get("trigger_at", ""), reverse=True)[:DONE_LIMIT]
        }
        payload["items"] = [
            item
            for item in payload.get("items", [])
            if item.get("status") != "done" or item.get("id") in keep_done_ids
        ]
        return payload


class SchedulerStateStore:
    """Persist last-send state for fixed daily jobs."""

    KEY_MAP = {
        "sleep_reminder": "sleep_reminder_last_sent_date",
        "tomorrow_schedule": "tomorrow_schedule_last_sent_date",
    }

    def __init__(self, path: str):
        self.store = JsonFileStore(path, self._default_payload)

    @staticmethod
    def _default_payload() -> dict[str, Any]:
        return {
            "sleep_reminder_last_sent_date": "",
            "tomorrow_schedule_last_sent_date": "",
            "meta": {},
        }

    def load_all(self) -> dict[str, Any]:
        payload = self._normalize_payload(self.store.load())
        print(f"[STORE] loaded scheduler_state keys={self._active_keys(payload)}")
        return payload

    def mark_daily_sent(self, task_key: str, token: str, sent_at: datetime) -> None:
        state_key = self.KEY_MAP.get(task_key, f"{task_key}_last_sent_date")

        def mutate(payload: dict[str, Any]) -> None:
            normalized = self._normalize_payload(payload)
            normalized[state_key] = token
            normalized.setdefault("meta", {})[f"{task_key}_last_sent_at"] = sent_at.isoformat()
            payload.clear()
            payload.update(normalized)
            return None

        self.store.mutate(mutate)
        print(f"[STORE] saved scheduler_state keys={self._active_keys(self.load_all())}")

    def was_daily_sent(self, task_key: str, token: str) -> bool:
        payload = self.load_all()
        state_key = self.KEY_MAP.get(task_key, f"{task_key}_last_sent_date")
        return str(payload.get(state_key, "")) == str(token)

    def _normalize_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        daily_tasks = payload.get("daily_tasks", {}) if isinstance(payload.get("daily_tasks"), dict) else {}
        normalized = self._default_payload()
        for task_key, state_key in self.KEY_MAP.items():
            if payload.get(state_key):
                normalized[state_key] = str(payload.get(state_key))
                continue
            record = daily_tasks.get(task_key, {})
            if isinstance(record, dict) and record.get("token"):
                normalized[state_key] = str(record.get("token"))
                normalized.setdefault("meta", {})[f"{task_key}_last_sent_at"] = record.get("sent_at")
        meta = payload.get("meta", {})
        if isinstance(meta, dict):
            normalized["meta"].update(meta)
        return normalized

    def _active_keys(self, payload: dict[str, Any]) -> list[str]:
        return [key for key in self.KEY_MAP.values() if payload.get(key)]
