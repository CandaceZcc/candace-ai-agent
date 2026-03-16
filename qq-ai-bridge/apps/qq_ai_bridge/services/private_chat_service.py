"""Private chat orchestration helpers."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR
from apps.qq_ai_bridge.services.prompt_service import build_private_ai_prompt, prepare_private_ai_prompt
from shared.ai.llm_client import call_ai
from storage_utils import (
    append_private_history,
    append_private_style_sample,
    get_user_workspace as ensure_user_workspace,
)

DEBOUNCE_MS = 1000


@dataclass
class PendingPrivateMessage:
    """Normalized private text waiting to be merged into one LLM request."""

    text: str
    timestamp: int


@dataclass
class PrivateChatState:
    """Per-user private chat single-flight state."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    pending: list[PendingPrivateMessage] = field(default_factory=list)
    last_enqueue_monotonic: float = 0.0
    debounce_started_monotonic: float = 0.0
    worker_running: bool = False


_PRIVATE_CHAT_STATES: dict[str, PrivateChatState] = {}
_PRIVATE_CHAT_STATES_LOCK = threading.Lock()


def get_user_workspace(user_id):
    """Ensure and return the per-user workspace."""
    return ensure_user_workspace(BASE_DATA_DIR, user_id)


def _get_private_chat_state(user_id) -> PrivateChatState:
    key = str(user_id)
    with _PRIVATE_CHAT_STATES_LOCK:
        state = _PRIVATE_CHAT_STATES.get(key)
        if state is None:
            state = PrivateChatState()
            _PRIVATE_CHAT_STATES[key] = state
        return state


def _merge_pending_messages(messages: list[PendingPrivateMessage]) -> tuple[str, int]:
    merged = [item.text.strip() for item in messages if item.text.strip()]
    return "\n".join(merged).strip(), len(merged)


def enqueue_private_text(user_id, ai_query: str, timestamp: int = 0) -> dict:
    """Queue private text so each user is processed serially with debounce."""
    state = _get_private_chat_state(user_id)
    pending_message = PendingPrivateMessage(text=ai_query, timestamp=timestamp)

    with state.lock:
        was_empty = not state.pending
        state.pending.append(pending_message)
        if was_empty:
            state.debounce_started_monotonic = time.monotonic()
        state.last_enqueue_monotonic = time.monotonic()
        pending_count = len(state.pending)
        worker_running = state.worker_running
        if not worker_running:
            state.worker_running = True
            worker = threading.Thread(target=_run_private_chat_worker, args=(user_id,), daemon=True)
            worker.start()

    print(
        f"[PRIVATE_CHAT] queued user_id={user_id}"
        f" pending_count={pending_count}"
        f" worker_running={worker_running}"
        f" debounce_ms={DEBOUNCE_MS}"
    )
    return {"queued": True, "pending_count": pending_count}


def _run_private_chat_worker(user_id) -> None:
    state = _get_private_chat_state(user_id)
    while True:
        with state.lock:
            if not state.pending:
                state.worker_running = False
                print(f"[PRIVATE_CHAT] idle user_id={user_id}")
                return
            wait_ms = max(0, int(DEBOUNCE_MS - (time.monotonic() - state.last_enqueue_monotonic) * 1000))

        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
            continue

        with state.lock:
            batch = state.pending[:]
            state.pending.clear()
            debounce_started_monotonic = state.debounce_started_monotonic
            state.debounce_started_monotonic = 0.0

        merged_text, merged_count = _merge_pending_messages(batch)
        if not merged_text:
            print(f"[PRIVATE_CHAT] skip-empty user_id={user_id} merged_count={merged_count}")
            continue

        debounce_window_ms = 0
        if debounce_started_monotonic:
            debounce_window_ms = int((time.monotonic() - debounce_started_monotonic) * 1000)

        print(
            f"[PRIVATE_CHAT] flushing user_id={user_id}"
            f" merged_message_count={merged_count}"
            f" debounce_window_ms={debounce_window_ms}"
        )

        get_user_workspace(user_id)
        current_message_ts = int(batch[-1].timestamp or 0)
        append_private_style_sample(BASE_DATA_DIR, user_id, merged_text, timestamp=current_message_ts or None)
        prompt_payload = prepare_private_ai_prompt(user_id, merged_text, current_timestamp=current_message_ts)
        print(
            f"[PRIVATE_CHAT] context_gap_seconds={prompt_payload['context_gap_seconds']}"
            f" user_id={user_id}"
        )
        print(
            f"[PRIVATE_CHAT] context_policy={prompt_payload['context_policy']}"
            f" reason={prompt_payload['context_reason']}"
            f" user_id={user_id}"
        )
        if prompt_payload["context_policy"] == "compact":
            print(
                f"[PRIVATE_CHAT] compact_trim"
                f" original_items={prompt_payload['original_history_items']}"
                f" original_chars={prompt_payload['original_history_chars']}"
                f" trimmed_items={prompt_payload['history_items']}"
                f" trimmed_chars={prompt_payload['history_chars']}"
                f" user_id={user_id}"
            )
        reply = call_ai(
            prompt_payload["prompt"],
            metadata={
                "user_id": user_id,
                "merged_message_count": merged_count,
                "prompt_mode": prompt_payload["prompt_mode"],
                "query_len": prompt_payload["query_len"],
                "history_chars": prompt_payload["history_chars"],
                "history_items": prompt_payload["history_items"],
                "instruction_chars": prompt_payload["instruction_chars"],
                "prompt_chars": prompt_payload["prompt_chars"],
            },
        )
        append_private_history(
            BASE_DATA_DIR,
            user_id,
            merged_text,
            reply,
            limit=20,
            user_timestamp=current_message_ts or None,
        )
        send_private_msg(user_id, reply)
        print(
            f"[PRIVATE_CHAT] replied user_id={user_id}"
            f" merged_message_count={merged_count}"
            f" prompt_mode={prompt_payload['prompt_mode']}"
            f" query_len={prompt_payload['query_len']}"
            f" history_chars={prompt_payload['history_chars']}"
            f" history_items={prompt_payload['history_items']}"
            f" instruction_chars={prompt_payload['instruction_chars']}"
            f" prompt_chars={prompt_payload['prompt_chars']}"
        )


__all__ = ["build_private_ai_prompt", "enqueue_private_text", "get_user_workspace"]
