"""Private chat orchestration helpers."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from shared.ai.llm_client import call_ai
from storage_utils import (
    append_private_history,
    append_private_style_sample,
)
from storage_utils import (
    get_user_workspace as ensure_user_workspace,
)

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR
from apps.qq_ai_bridge.services.emoji_service import (
    DEFAULT_REACTION_ORDER,
    build_face_cq,
    build_face_sequence,
    detect_emoji_request_count,
    extract_emoji_name,
    is_face_fallback_request,
    is_message_reaction_request,
    is_emoji_request,
    pick_face_cq,
)
from apps.qq_ai_bridge.services.prompt_service import (
    build_private_ai_prompt,
    prepare_private_ai_prompt,
)
from apps.qq_ai_bridge.services.response_action import (
    ActionKind,
    ResponseAction,
    execute_private_action,
    parse_llm_response_action,
)

DEBOUNCE_MS = 1000
PRIVATE_REACTION_MIRROR_FACE = False


@dataclass
class PendingPrivateMessage:
    """Normalized private text waiting to be merged into one LLM request."""

    text: str
    timestamp: int
    message_id: int | None = None


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


# get_user_workspace：获取用户工作目录
def get_user_workspace(user_id):
    """Ensure and return the per-user workspace."""
    return ensure_user_workspace(BASE_DATA_DIR, user_id)


# _handle_private_emoji_request：处理私聊表情请求
def _handle_private_emoji_request(user_id, merged_text: str, current_message_ts: int, message_id: int | None) -> dict:
    """Handle explicit private emoji requests with safe CQ fallback."""
    if not is_emoji_request(merged_text):
        return {"handled": False}

    count = detect_emoji_request_count(merged_text, default_count=1, max_count=4)
    seed = f"{user_id}:{current_message_ts}:{merged_text}"
    if message_id and is_message_reaction_request(merged_text):
        action_result = execute_private_action(
            user_id,
            ResponseAction(
                kind=ActionKind.REACTION,
                reaction_count=count,
                preferred_order=DEFAULT_REACTION_ORDER,
                reason="private_emoji_request",
            ),
            target_message_id=message_id,
            quiet=False,
            reaction_fallback_reply_face=True,
        )
        if action_result.get("ok") and int(action_result.get("applied_count", 0)) > 0:
            return {
                "handled": True,
                "mode": "reaction",
                "chosen_name": "reaction",
                "applied_count": int(action_result.get("applied_count", 0)),
            }

    if not is_face_fallback_request(merged_text):
        return {"handled": False}

    requested_name = extract_emoji_name(merged_text)
    if requested_name:
        face_message = "\n\n".join([build_face_cq(requested_name) or "[CQ:face,id=182]" for _ in range(max(1, count))])
        chosen_name = requested_name
    elif count <= 1:
        chosen_name, face_message = pick_face_cq(seed=seed)
    else:
        chosen_name = "mixed"
        face_message = "\n\n".join(build_face_sequence(seed=seed, count=count))
    send_private_msg(user_id, face_message)
    return {"handled": True, "mode": "face_fallback", "chosen_name": chosen_name, "applied_count": 0}


# _get_private_chat_state：获取私聊聊天状态
def _get_private_chat_state(user_id) -> PrivateChatState:
    key = str(user_id)
    with _PRIVATE_CHAT_STATES_LOCK:
        state = _PRIVATE_CHAT_STATES.get(key)
        if state is None:
            state = PrivateChatState()
            _PRIVATE_CHAT_STATES[key] = state
        return state


# _merge_pending_messages：待办消息处理
def _merge_pending_messages(messages: list[PendingPrivateMessage]) -> tuple[str, int]:
    merged = [item.text.strip() for item in messages if item.text.strip()]
    return "\n".join(merged).strip(), len(merged)


# enqueue_private_text：私聊文本入队合并
def enqueue_private_text(user_id, ai_query: str, timestamp: int = 0, message_id: int | None = None) -> dict:
    """Queue private text so each user is processed serially with debounce."""
    state = _get_private_chat_state(user_id)
    pending_message = PendingPrivateMessage(text=ai_query, timestamp=timestamp, message_id=message_id)

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


# _run_private_chat_worker：运行私聊消费线程
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
        current_message_id = batch[-1].message_id
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
        # Explicit emoji request in private chat should be handled directly.
        if is_emoji_request(merged_text):
            emoji_result = _handle_private_emoji_request(user_id, merged_text, current_message_ts, current_message_id)
            chosen_name = str(emoji_result.get("chosen_name") or "emoji")
            append_private_history(
                BASE_DATA_DIR,
                user_id,
                merged_text,
                f"[emoji:{chosen_name}]",
                limit=20,
                user_timestamp=current_message_ts or None,
            )
            print(
                f"[PRIVATE_CHAT] emoji_replied user_id={user_id}"
                f" emoji={chosen_name}"
                f" message_id={current_message_id}"
                f" mode={emoji_result.get('mode')}"
            )
            continue
        llm_raw_reply = call_ai(
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
        llm_action = parse_llm_response_action(llm_raw_reply)
        if llm_action.kind == ActionKind.NO_REPLY:
            execute_private_action(
                user_id,
                ResponseAction(kind=ActionKind.NO_REPLY, reason="llm_no_reply"),
                target_message_id=None,
                quiet=False,
            )
            print(f"[PRIVATE_CHAT] no_reply user_id={user_id}")
            continue
        if llm_action.kind == ActionKind.REACTION:
            action_result = execute_private_action(
                user_id,
                llm_action,
                target_message_id=current_message_id,
                quiet=False,
                reaction_fallback_reply_face=not PRIVATE_REACTION_MIRROR_FACE,
            )
            if action_result.get("ok"):
                print(
                    f"[PRIVATE_CHAT] llm_action=reaction user_id={user_id}"
                    f" message_id={current_message_id}"
                    f" applied_count={action_result.get('applied_count', 0)}"
                )
                continue
        reply = llm_action.text
        append_private_history(
            BASE_DATA_DIR,
            user_id,
            merged_text,
            llm_action.text,
            limit=20,
            user_timestamp=current_message_ts or None,
        )
        execute_private_action(
            user_id,
            llm_action,
            target_message_id=None,
            quiet=False,
        )
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
