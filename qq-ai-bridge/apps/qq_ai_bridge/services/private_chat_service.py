"""Private chat orchestration helpers."""

from __future__ import annotations

import asyncio
import threading
import time
from dataclasses import dataclass, field

from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime
from shared.ai.llm_client import call_ai
from storage_utils import (
    append_private_history,
    append_private_style_sample,
)
from storage_utils import (
    get_user_workspace as ensure_user_workspace,
)

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.config.settings import (
    AGENT_RUNTIME_ENABLED,
    BASE_DATA_DIR,
    CHAT_STATE_TTL_SECONDS,
    OWNER_QQ,
    PRIVATE_COOLDOWN_MODE,
    PRIVATE_DEBOUNCE_MS,
    PRIVATE_REPLY_COOLDOWN_SEC,
)
from apps.qq_ai_bridge.services.agent_route_service import classify_agent_route
from apps.qq_ai_bridge.services.emoji_service import (
    build_face_cq,
    build_face_sequence,
    detect_emoji_request_count,
    extract_emoji_name,
    infer_reaction_preferred_order,
    is_emoji_request,
    is_face_fallback_request,
    is_message_reaction_request,
    pick_face_cq,
)
from apps.qq_ai_bridge.services.private_ledger_service import maybe_handle_private_ledger_command
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
from apps.qq_ai_bridge.services.runtime_resources import submit_chat_task

DEBOUNCE_MS = PRIVATE_DEBOUNCE_MS
PRIVATE_REACTION_MIRROR_FACE = False
AGENT_COMPACT_CONTEXT_MAX_CHARS = 4000
_AGENT_RUNTIME_LOOP_LOCK = threading.Lock()
_AGENT_RUNTIME_LOOP: asyncio.AbstractEventLoop | None = None
_AGENT_RUNTIME_LOOP_THREAD: threading.Thread | None = None


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
    last_reply_monotonic: float = 0.0
    last_activity_monotonic: float = field(default_factory=time.monotonic)


_PRIVATE_CHAT_STATES: dict[str, PrivateChatState] = {}
_PRIVATE_CHAT_STATES_LOCK = threading.Lock()
_PRIVATE_CHAT_STATES_LAST_CLEANUP = 0.0
_PRIVATE_CHAT_STATES_CLEANUP_INTERVAL_SECONDS = 60.0


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
                preferred_order=infer_reaction_preferred_order(merged_text),
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
    _maybe_cleanup_private_chat_states()
    key = str(user_id)
    with _PRIVATE_CHAT_STATES_LOCK:
        state = _PRIVATE_CHAT_STATES.get(key)
        if state is None:
            state = PrivateChatState()
            _PRIVATE_CHAT_STATES[key] = state
        state.last_activity_monotonic = time.monotonic()
        return state


def _maybe_cleanup_private_chat_states(now: float | None = None) -> int:
    global _PRIVATE_CHAT_STATES_LAST_CLEANUP
    current = time.monotonic() if now is None else float(now)
    if current - _PRIVATE_CHAT_STATES_LAST_CLEANUP < _PRIVATE_CHAT_STATES_CLEANUP_INTERVAL_SECONDS:
        return 0
    _PRIVATE_CHAT_STATES_LAST_CLEANUP = current
    return _cleanup_private_chat_states(now=current)


def _cleanup_private_chat_states(
    *,
    now: float | None = None,
    ttl_seconds: float | None = None,
) -> int:
    current = time.monotonic() if now is None else float(now)
    ttl = float(CHAT_STATE_TTL_SECONDS if ttl_seconds is None else ttl_seconds)
    removed = 0
    with _PRIVATE_CHAT_STATES_LOCK:
        for key, state in list(_PRIVATE_CHAT_STATES.items()):
            with state.lock:
                if state.worker_running or state.pending:
                    continue
                if current - state.last_activity_monotonic < ttl:
                    continue
                _PRIVATE_CHAT_STATES.pop(key, None)
                removed += 1
    return removed


def get_private_chat_runtime_status() -> dict[str, int]:
    with _PRIVATE_CHAT_STATES_LOCK:
        states = list(_PRIVATE_CHAT_STATES.values())
    return {
        "states": len(states),
        "active_workers": sum(1 for state in states if state.worker_running),
        "pending_messages": sum(len(state.pending) for state in states),
    }


# _merge_pending_messages：待办消息处理
def _merge_pending_messages(messages: list[PendingPrivateMessage]) -> tuple[str, int]:
    merged = [item.text.strip() for item in messages if item.text.strip()]
    return "\n".join(merged).strip(), len(merged)


def _cooldown_remaining_seconds(state: PrivateChatState) -> float:
    if PRIVATE_REPLY_COOLDOWN_SEC <= 0 or state.last_reply_monotonic <= 0:
        return 0.0
    elapsed = time.monotonic() - state.last_reply_monotonic
    return max(0.0, float(PRIVATE_REPLY_COOLDOWN_SEC) - elapsed)


def _record_private_reply_sent(state: PrivateChatState) -> None:
    with state.lock:
        state.last_reply_monotonic = time.monotonic()


def _generate_private_model_reply(
    user_id: int,
    merged_text: str,
    prompt_payload: dict,
    *,
    merged_count: int,
    trace_id: str | None,
) -> str:
    if not AGENT_RUNTIME_ENABLED or int(user_id or 0) != int(OWNER_QQ):
        return _call_legacy_private_ai(user_id, prompt_payload, merged_count)

    decision = classify_agent_route(merged_text)
    if not decision.use_general_agent:
        return "邮件功能正在接入中，这条命令稍后会由邮件技能处理。"

    request = AgentRunRequest(
        route=decision.route,
        user_text=merged_text,
        compact_context=_build_agent_compact_context(prompt_payload),
        allowed_tool_names=decision.allowed_tool_names,
        trace_id=trace_id,
    )
    result = run_agent_runtime_sync(AgentRuntime(legacy_call=call_ai).run(request))
    return result.output_text


def _call_legacy_private_ai(user_id: int, prompt_payload: dict, merged_count: int) -> str:
    return call_ai(
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


def _build_agent_compact_context(prompt_payload: dict) -> str:
    prompt = str(prompt_payload.get("prompt") or "")
    return prompt[:AGENT_COMPACT_CONTEXT_MAX_CHARS]


def run_agent_runtime_sync(coro):
    loop = _get_agent_runtime_loop()
    return asyncio.run_coroutine_threadsafe(coro, loop).result()


_run_agent_runtime_sync = run_agent_runtime_sync


def _get_agent_runtime_loop() -> asyncio.AbstractEventLoop:
    global _AGENT_RUNTIME_LOOP, _AGENT_RUNTIME_LOOP_THREAD

    with _AGENT_RUNTIME_LOOP_LOCK:
        if (
            _AGENT_RUNTIME_LOOP is not None
            and _AGENT_RUNTIME_LOOP_THREAD is not None
            and _AGENT_RUNTIME_LOOP_THREAD.is_alive()
        ):
            return _AGENT_RUNTIME_LOOP

        loop = asyncio.new_event_loop()
        ready = threading.Event()

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            ready.set()
            loop.run_forever()

        thread = threading.Thread(target=run_loop, name="agent-runtime-loop", daemon=True)
        thread.start()
        ready.wait()
        _AGENT_RUNTIME_LOOP = loop
        _AGENT_RUNTIME_LOOP_THREAD = thread
        return loop


# enqueue_private_text：私聊文本入队合并
def enqueue_private_text(user_id, ai_query: str, timestamp: int = 0, message_id: int | None = None) -> dict:
    """Queue private text so each user is processed serially with debounce."""
    state = _get_private_chat_state(user_id)
    pending_message = PendingPrivateMessage(text=ai_query, timestamp=timestamp, message_id=message_id)

    with state.lock:
        state.last_activity_monotonic = time.monotonic()
        was_empty = not state.pending
        state.pending.append(pending_message)
        if was_empty:
            state.debounce_started_monotonic = time.monotonic()
        state.last_enqueue_monotonic = time.monotonic()
        pending_count = len(state.pending)
        worker_running = state.worker_running
        if not worker_running:
            state.worker_running = True
            future = submit_chat_task(_run_private_chat_worker_safely, user_id)
            if future is None:
                state.pending.remove(pending_message)
                state.worker_running = False
                return {"queued": False, "reason": "runtime_busy"}

    print(
        f"[PRIVATE_CHAT] queued user_id={user_id}"
        f" pending_count={pending_count}"
        f" worker_running={worker_running}"
        f" debounce_ms={DEBOUNCE_MS}"
    )
    return {"queued": True, "pending_count": pending_count}


# _run_private_chat_worker_safely：隔离异常并恢复会话状态
def _run_private_chat_worker_safely(user_id) -> None:
    try:
        _run_private_chat_worker(user_id)
    except Exception as exc:
        state = _get_private_chat_state(user_id)
        with state.lock:
            dropped_pending = len(state.pending)
            state.pending.clear()
            state.worker_running = False
            state.debounce_started_monotonic = 0.0
            state.last_activity_monotonic = time.monotonic()
        print(
            f"[PRIVATE_CHAT] worker_failed user_id={user_id}"
            f" error_type={type(exc).__name__}"
            f" dropped_pending={dropped_pending}"
        )
        send_private_msg(user_id, "消息处理失败了，请稍后重试。", quiet=True)


# _run_private_chat_worker：运行私聊消费线程
def _run_private_chat_worker(user_id) -> None:
    state = _get_private_chat_state(user_id)
    while True:
        with state.lock:
            if not state.pending:
                state.worker_running = False
                state.last_activity_monotonic = time.monotonic()
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
        ledger_result = maybe_handle_private_ledger_command(user_id, merged_text)
        if ledger_result and ledger_result.get("handled"):
            reply = str(ledger_result.get("reply") or "").strip()
            history_reply = str(ledger_result.get("history_reply") or reply)
            append_private_history(
                BASE_DATA_DIR,
                user_id,
                merged_text,
                history_reply,
                limit=20,
                user_timestamp=current_message_ts or None,
            )
            execute_private_action(
                user_id,
                ResponseAction(kind=ActionKind.TEXT, text=reply, reason="private_ledger"),
                target_message_id=None,
                quiet=False,
                force_parts=ledger_result.get("force_parts"),
            )
            _record_private_reply_sent(state)
            print(
                f"[PRIVATE_LEDGER] {ledger_result.get('mode', 'handled')}"
                f" user_id={user_id}"
                f" parts_total={ledger_result.get('parts_total', 1)}"
                f" summary={ledger_result.get('summary', '')!r}"
            )
            continue
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
        cooldown_remaining = _cooldown_remaining_seconds(state)
        if cooldown_remaining > 0 and PRIVATE_COOLDOWN_MODE == "record_only":
            append_private_history(
                BASE_DATA_DIR,
                user_id,
                merged_text,
                "[cooldown_skip]",
                limit=20,
                user_timestamp=current_message_ts or None,
            )
            print(
                f"[PRIVATE_CHAT] cooldown_skip user_id={user_id}"
                f" remaining_sec={cooldown_remaining:.1f}"
                f" merged_message_count={merged_count}"
                f" mode={PRIVATE_COOLDOWN_MODE}"
            )
            continue
        llm_raw_reply = _generate_private_model_reply(
            user_id,
            merged_text,
            prompt_payload,
            merged_count=merged_count,
            trace_id=None,
        )
        llm_action = parse_llm_response_action(llm_raw_reply, surface="private")
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
                _record_private_reply_sent(state)
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
        _record_private_reply_sent(state)
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


__all__ = [
    "build_private_ai_prompt",
    "enqueue_private_text",
    "get_user_workspace",
    "run_agent_runtime_sync",
]
