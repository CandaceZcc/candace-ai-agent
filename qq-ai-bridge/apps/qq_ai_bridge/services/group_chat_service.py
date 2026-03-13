"""Group chat orchestration helpers."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text
from apps.qq_ai_bridge.adapters.napcat_client import send_group_msg
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR, GROUP_CONFIG_PATH
from apps.qq_ai_bridge.services.prompt_service import prepare_group_ai_prompt
from shared.ai.llm_client import call_ai
from storage_utils import load_group_config as load_group_config_from_file

GROUP_DEBOUNCE_MS = 5000


@dataclass
class PendingGroupMessage:
    """Normalized group text waiting to be merged into one reply."""

    user_id: int | None
    sender_name: str
    text: str
    timestamp: int
    explicit_trigger: bool = False


@dataclass
class GroupChatState:
    """Per-group single-flight state."""

    lock: threading.Lock = field(default_factory=threading.Lock)
    pending: list[PendingGroupMessage] = field(default_factory=list)
    last_enqueue_monotonic: float = 0.0
    debounce_started_monotonic: float = 0.0
    worker_running: bool = False


_GROUP_CHAT_STATES: dict[str, GroupChatState] = {}
_GROUP_CHAT_STATES_LOCK = threading.Lock()


def load_group_config(group_id) -> dict:
    """Load merged group config for a specific QQ group."""
    return load_group_config_from_file(GROUP_CONFIG_PATH, group_id)


def should_log_group(group_id) -> bool:
    """Return whether logs should be printed for a group."""
    cfg = load_group_config(group_id)
    return not cfg.get("ignore", False) and not cfg.get("mute_log", False)


def enqueue_group_text(
    group_id,
    user_id,
    sender_name: str,
    ai_query: str,
    group_config: dict,
    explicit_trigger: bool,
    timestamp: int = 0,
    log=print,
) -> dict:
    """Queue group text so one group is processed with a shared debounce window."""
    normalized_text = normalize_query_text(ai_query)
    if not normalized_text:
        return {"queued": False, "reason": "empty_text"}

    state = _get_group_chat_state(group_id)
    pending_message = PendingGroupMessage(
        user_id=user_id,
        sender_name=(sender_name or str(user_id or "?")).strip(),
        text=normalized_text,
        timestamp=timestamp,
        explicit_trigger=bool(explicit_trigger),
    )

    with state.lock:
        already_buffering = bool(state.pending) or state.worker_running
        reply_all = bool(group_config.get("reply_all_messages", False))
        if not explicit_trigger and not reply_all and not already_buffering:
            return {"queued": False, "reason": "group_not_triggered"}

        was_empty = not state.pending
        state.pending.append(pending_message)
        if was_empty:
            state.debounce_started_monotonic = time.monotonic()
        state.last_enqueue_monotonic = time.monotonic()
        pending_count = len(state.pending)
        worker_running = state.worker_running
        if not worker_running:
            state.worker_running = True
            worker = threading.Thread(target=_run_group_chat_worker, args=(group_id, group_config, log), daemon=True)
            worker.start()

    log(
        f"[GROUP_CHAT] queued group_id={group_id}"
        f" pending_count={pending_count}"
        f" explicit_trigger={explicit_trigger}"
        f" worker_running={worker_running}"
        f" debounce_ms={GROUP_DEBOUNCE_MS}"
    )
    return {
        "queued": True,
        "pending_count": pending_count,
        "explicit_trigger": bool(explicit_trigger),
    }


def _get_group_chat_state(group_id) -> GroupChatState:
    key = str(group_id)
    with _GROUP_CHAT_STATES_LOCK:
        state = _GROUP_CHAT_STATES.get(key)
        if state is None:
            state = GroupChatState()
            _GROUP_CHAT_STATES[key] = state
        return state


def _run_group_chat_worker(group_id, group_config: dict, log) -> None:
    state = _get_group_chat_state(group_id)
    while True:
        with state.lock:
            if not state.pending:
                state.worker_running = False
                log(f"[GROUP_CHAT] idle group_id={group_id}")
                return
            wait_ms = max(0, int(GROUP_DEBOUNCE_MS - (time.monotonic() - state.last_enqueue_monotonic) * 1000))

        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
            continue

        with state.lock:
            batch = state.pending[:]
            state.pending.clear()
            debounce_started_monotonic = state.debounce_started_monotonic
            state.debounce_started_monotonic = 0.0

        merged_batch = _merge_pending_group_messages(batch)
        merged_text = merged_batch["prompt_text"]
        merged_count = merged_batch["message_count"]
        user_count = merged_batch["user_count"]

        if not merged_text:
            log(f"[GROUP_CHAT] skip-empty group_id={group_id} merged_count={merged_count}")
            continue

        debounce_window_ms = 0
        if debounce_started_monotonic:
            debounce_window_ms = int((time.monotonic() - debounce_started_monotonic) * 1000)

        log(
            f"[GROUP_CHAT] flushing group_id={group_id}"
            f" merged_message_count={merged_count}"
            f" merged_user_count={user_count}"
            f" debounce_window_ms={debounce_window_ms}"
        )

        prompt_payload = prepare_group_ai_prompt(
            group_id,
            merged_text,
            user_id=batch[-1].user_id,
            log=log,
            batch_context=merged_batch,
        )
        reply = call_ai(
            prompt_payload["prompt"],
            metadata={
                "user_id": f"group:{group_id}",
                "merged_message_count": merged_count,
                "prompt_mode": prompt_payload["prompt_mode"],
                "query_len": prompt_payload["query_len"],
                "history_chars": prompt_payload["history_chars"],
                "history_items": prompt_payload["history_items"],
                "instruction_chars": prompt_payload["instruction_chars"],
                "prompt_chars": prompt_payload["prompt_chars"],
            },
        )
        send_group_msg(group_id, reply, quiet=not should_log_group(group_id))
        log(
            f"[GROUP_CHAT] replied group_id={group_id}"
            f" merged_message_count={merged_count}"
            f" merged_user_count={user_count}"
            f" prompt_mode={prompt_payload['prompt_mode']}"
            f" query_len={prompt_payload['query_len']}"
            f" history_chars={prompt_payload['history_chars']}"
            f" history_items={prompt_payload['history_items']}"
            f" md_chars={prompt_payload.get('markdown_chars', 0)}"
            f" instruction_chars={prompt_payload['instruction_chars']}"
            f" prompt_chars={prompt_payload['prompt_chars']}"
        )


def _merge_pending_group_messages(messages: list[PendingGroupMessage]) -> dict:
    merged_blocks: list[dict] = []
    raw_messages = 0

    for item in messages:
        text = normalize_query_text(item.text)
        if not text:
            continue
        raw_messages += 1
        sender_name = item.sender_name or str(item.user_id or "?")
        if merged_blocks and merged_blocks[-1]["user_id"] == item.user_id:
            merged_blocks[-1]["texts"].append(text)
            continue
        merged_blocks.append(
            {
                "user_id": item.user_id,
                "sender_name": sender_name,
                "texts": [text],
            }
        )

    lines = []
    for block in merged_blocks:
        merged_line = " | ".join(block["texts"]).strip()
        if not merged_line:
            continue
        lines.append(f"{block['sender_name']}：{merged_line}")

    return {
        "prompt_text": "\n".join(lines).strip(),
        "message_count": raw_messages,
        "user_count": len({str(block['user_id']) for block in merged_blocks}),
        "merged_blocks": merged_blocks,
    }

