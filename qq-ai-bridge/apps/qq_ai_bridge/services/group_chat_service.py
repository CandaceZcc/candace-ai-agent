"""Group chat orchestration helpers."""

from __future__ import annotations

import json
import hashlib
import os
import threading
import time
from dataclasses import dataclass, field
import re

from shared.ai.llm_client import call_ai
from storage_utils import append_group_chat_log
from storage_utils import load_group_config as load_group_config_from_file

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text
from apps.qq_ai_bridge.adapters.napcat_client import send_group_file
from apps.qq_ai_bridge.config.settings import GROUP_CONFIG_PATH
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR
from apps.qq_ai_bridge.config.settings import GLOBAL_LISTEN_GROUP_IDS
from apps.qq_ai_bridge.services.emoji_service import infer_reaction_preferred_order
from apps.qq_ai_bridge.services.group_strategy import normalize_group_strategy_config, record_group_strategy_reply
from apps.qq_ai_bridge.services.prompt_service import prepare_group_ai_prompt
from apps.qq_ai_bridge.services.response_action import (
    ActionKind,
    ResponseAction,
    execute_group_action,
    parse_llm_response_action,
)
from apps.qq_ai_bridge.services.trace_store import add_trace_step

GROUP_DEBOUNCE_MS = 5000
_DEFAULT_GROUP_DEBOUNCE_MS = GROUP_DEBOUNCE_MS
GENERATED_GROUP_FILE_DIR = os.path.join(BASE_DATA_DIR, "generated_files", "group")
_CODE_BLOCK_PATTERN = re.compile(r"```([a-zA-Z0-9_+.-]*)\n(.*?)```", re.DOTALL)
_CODE_REQUEST_PATTERN = re.compile(
    r"(写|生成|做|来|整|给).*?(程序|代码|脚本|网页|html|python|py|js|javascript|typescript|ts|css|爬虫|bot)|"
    r"(程序|代码|脚本|网页|html|python|py|js|javascript|typescript|ts|css|爬虫|bot).*?(写|生成|做|来|整|给)",
    re.IGNORECASE,
)
_CODE_LIKE_PATTERN = re.compile(r"(def |class |function |import |from |const |let |var |<!DOCTYPE|<html|#include|public class |package )")
_DANGEROUS_FILE_REQUEST_PATTERN = re.compile(
    r"(rm\s+-rf\s+/|/下的都删|删掉\s*/|删除\s*/|格式化|清空磁盘|"
    r"api[_-]?key|secret|token|密码|密钥|配置文件.*发|env|\.env|"
    r"关机|shutdown\s+/s|重启|reboot|按\s*win\s*\+\s*r|输入\s*cmd|"
    r"列出.*文件|文件.*发过来|发过来.*文件|发送.*文件夹|所有文件|"
    r"/home/[^\s`'\"]+|~/.openclaw|openclaw|workspace)",
    re.IGNORECASE,
)
_HEAVY_CODE_REQUEST_PATTERN = re.compile(r"(\d+)\s*(行|lines?|代码)", re.IGNORECASE)
_REPLY_FILLER_PATTERN = re.compile(r"(?:^|\s)(确实|草|牛逼|典|寄了?|救命|贴贴)(?:\s+\1)+", re.IGNORECASE)
_REPLY_LOOP_PATTERN = re.compile(r"^(确实|草|牛逼|典|寄了?|救命|贴贴)(\s+(确实|草|牛逼|典|寄了?|救命|贴贴))*$", re.IGNORECASE)


@dataclass
class PendingGroupMessage:
    """Normalized group text waiting to be merged into one reply."""

    user_id: int | None
    sender_name: str
    text: str
    timestamp: int
    message_id: int | None = None
    reply_reference: dict | None = None
    explicit_trigger: bool = False
    strategy: dict | None = None
    trace_id: str = ""


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
_RECENT_REPEAT_MESSAGES: dict[str, list[tuple[float, str]]] = {}
_RECENT_REPEAT_FOLLOWS: dict[str, float] = {}
_REPEAT_FOLLOW_COOLDOWN_SECONDS = 60
_REPEAT_FOLLOW_WINDOW_SECONDS = 45
_REPEAT_FOLLOW_MIN_COUNT = 3
_REPEAT_FOLLOW_MAX_CHARS = 80
_TURN_EXTENSION_SECONDS = 2.0
_TURN_EXTENSION_MAX_WINDOW_SECONDS = 8.0
_AMBIENT_CHATTER_REPLY_THRESHOLD = 20
_ZH_NUM_MAP = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}

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
    message_id: int | None = None,
    reply_reference: dict | None = None,
    strategy: dict | None = None,
    trace_id: str | None = None,
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
        message_id=message_id,
        reply_reference=reply_reference,
        explicit_trigger=bool(explicit_trigger),
        strategy=strategy if isinstance(strategy, dict) else None,
        trace_id=str(trace_id or ""),
    )
    strategy_cfg = normalize_group_strategy_config(group_config)
    context_window_ms = _context_window_ms(strategy_cfg)

    with state.lock:
        configured_reply_all = bool(group_config.get("reply_all_messages", False))
        fallback_global_listen = int(group_id or 0) in GLOBAL_LISTEN_GROUP_IDS
        reply_all = configured_reply_all or fallback_global_listen
        # In mention-only groups, never auto-absorb follow-up messages
        # just because a worker is running; each message must be explicitly triggered.
        if not explicit_trigger and not reply_all:
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
        f" debounce_ms={context_window_ms}"
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
    strategy_cfg = normalize_group_strategy_config(group_config)
    context_window_ms = _context_window_ms(strategy_cfg)
    while True:
        with state.lock:
            if not state.pending:
                state.worker_running = False
                log(f"[GROUP_CHAT] idle group_id={group_id}")
                return
            if _should_flush_head_message_now(state.pending):
                wait_ms = 0
            else:
                wait_ms = max(0, int(context_window_ms - (time.monotonic() - state.last_enqueue_monotonic) * 1000))

        if wait_ms > 0:
            time.sleep(wait_ms / 1000.0)
            continue

        with state.lock:
            extension_ms = _compute_turn_extension_ms(
                state.pending,
                state.debounce_started_monotonic,
                max_window_seconds=strategy_cfg["context_window_sec"],
            )
        if extension_ms > 0:
            time.sleep(extension_ms / 1000.0)
            continue

        with state.lock:
            if _should_flush_head_message_now(state.pending):
                batch = state.pending[:1]
                state.pending = state.pending[1:]
            else:
                batch_size = _select_group_batch_size(state.pending)
                batch = state.pending[:batch_size]
                state.pending = state.pending[batch_size:]
            if state.pending:
                state.debounce_started_monotonic = time.monotonic()
                state.last_enqueue_monotonic = time.monotonic()
            debounce_started_monotonic = state.debounce_started_monotonic
            if not state.pending:
                state.debounce_started_monotonic = 0.0

        merged_batch = _merge_pending_group_messages(batch)
        merged_text = merged_batch["prompt_text"]
        merged_count = merged_batch["message_count"]
        user_count = merged_batch["user_count"]
        trace_id = _pick_batch_trace_id(batch)
        add_trace_step(trace_id, "group_context", group_id=group_id, messages=merged_count, window_sec=strategy_cfg["context_window_sec"])

        if not merged_text:
            log(f"[GROUP_CHAT] skip-empty group_id={group_id} merged_count={merged_count}")
            continue

        debounce_window_ms = 0
        if debounce_started_monotonic:
            debounce_window_ms = int((time.monotonic() - debounce_started_monotonic) * 1000)

        log(
            f"[GROUP_CONTEXT] messages={merged_count} window={strategy_cfg['context_window_sec']}s "
            f"group_id={group_id}"
        )
        log(
            f"[GROUP_CHAT] flushing group_id={group_id}"
            f" merged_message_count={merged_count}"
            f" merged_user_count={user_count}"
            f" debounce_window_ms={debounce_window_ms}"
        )

        safety_action = _build_group_safety_action(merged_text)
        if safety_action:
            reply_to_message_id = _pick_text_reply_target_message_id(batch, safety_action.text)
            action_result = execute_group_action(
                group_id,
                safety_action,
                target_message_id=None,
                quiet=not should_log_group(group_id),
                reply_to_message_id=reply_to_message_id,
            )
            if action_result.get("ok"):
                record_group_strategy_reply(group_id)
            log(
                f"[GROUP_CHAT] safety_blocked group_id={group_id}"
                f" reason={safety_action.reason!r} reply_to_message_id={reply_to_message_id or '-'}"
            )
            continue

        repeat_text, repeat_count = _detect_repeat_follow_text(group_id, batch)
        if repeat_text and _claim_repeat_follow(group_id, repeat_text):
            action_result = execute_group_action(
                group_id,
                ResponseAction(kind=ActionKind.TEXT, text=repeat_text, reason="repeat_follow"),
                target_message_id=None,
                quiet=not should_log_group(group_id),
            )
            if action_result.get("ok"):
                record_group_strategy_reply(group_id)
                append_group_chat_log(
                    BASE_DATA_DIR,
                    group_id,
                    {
                        "timestamp": int(batch[-1].timestamp or 0) if batch else 0,
                        "sender_name": "群聊复读",
                        "user_id": batch[-1].user_id if batch else None,
                        "message": repeat_text,
                        "assistant": repeat_text,
                        "source": "group_chat:repeat_follow",
                    },
                    limit=500,
                )
                log(
                    f"[GROUP_CHAT] repeat_followed group_id={group_id}"
                    f" count={repeat_count} text={repeat_text!r}"
                )
                continue
            log(
                f"[GROUP_CHAT] repeat_follow_failed group_id={group_id}"
                f" count={repeat_count} text={repeat_text!r}"
            )

        strategy = _pick_batch_strategy(batch)
        strategy_mode = str(strategy.get("mode") or "")
        global_listen_mode = _is_global_listen_group(group_id, group_config)
        direct_react_count = _detect_direct_reaction_request_count(merged_text)
        decision_mode = _get_reaction_decision_mode(group_config)
        if direct_react_count > 0 and decision_mode in {"rule_first", "hybrid", "llm_first"}:
            target_message_id = _pick_reaction_target_message_id(batch)
            if target_message_id:
                action_result = execute_group_action(
                    group_id,
                    ResponseAction(
                        kind=ActionKind.REACTION,
                        reaction_count=direct_react_count,
                        preferred_order=infer_reaction_preferred_order(merged_text),
                        reason="direct_reaction_request",
                    ),
                    target_message_id=target_message_id,
                    quiet=not should_log_group(group_id),
                )
                reacted = int(action_result.get("applied_count", 0))
                if reacted > 0:
                    record_group_strategy_reply(group_id)
                    log(
                        f"[GROUP_CHAT] direct_reacted group_id={group_id} "
                        f"message_id={target_message_id} count={reacted}"
                    )
                    continue

        if global_listen_mode and strategy_mode not in {"text", "delay_text"}:
            llm_decision = _decide_group_response_mode_with_llm(
                merged_text=merged_text,
                batch=batch,
                group_config=group_config,
                log=log,
            )
            if llm_decision["mode"] == "silence":
                action_result = execute_group_action(
                    group_id,
                    ResponseAction(kind=ActionKind.NO_REPLY, reason=llm_decision.get("reason", "")),
                    target_message_id=None,
                    quiet=not should_log_group(group_id),
                )
                if action_result.get("ok"):
                    log(
                        f"[GROUP_CHAT] llm_decision=silence group_id={group_id}"
                        f" reason={llm_decision.get('reason', '')}"
                    )
                    continue
            if llm_decision["mode"] == "reaction":
                target_message_id = _pick_reaction_target_message_id(batch)
                if target_message_id:
                    action_result = execute_group_action(
                        group_id,
                        ResponseAction(
                            kind=ActionKind.REACTION,
                            reaction_count=1,
                            preferred_order=infer_reaction_preferred_order(merged_text),
                            reason=llm_decision.get("reason", ""),
                        ),
                        target_message_id=target_message_id,
                        quiet=not should_log_group(group_id),
                    )
                    if action_result.get("ok"):
                        record_group_strategy_reply(group_id)
                        log(
                            f"[GROUP_CHAT] llm_decision=reaction group_id={group_id}"
                            f" message_id={target_message_id}"
                            f" applied_count={action_result.get('applied_count', 0)}"
                            f" reason={llm_decision.get('reason', '')}"
                        )
                        continue
                    log(
                        f"[GROUP_CHAT] llm_reaction_failed group_id={group_id}"
                        f" message_id={target_message_id}"
                        f" reason={llm_decision.get('reason', '')}"
                    )
                else:
                    log(f"[GROUP_CHAT] llm_reaction_skipped_missing_message_id group_id={group_id}")
        elif global_listen_mode:
            log(
                f"[GROUP_CHAT] strategy_mode_override group_id={group_id}"
                f" mode={strategy_mode} skip=group_response_mode"
            )

        prompt_payload = prepare_group_ai_prompt(
            group_id,
            merged_text,
            user_id=batch[-1].user_id if batch else None,
            log=log,
            batch_context=merged_batch,
            group_config=group_config,
        )
        llm_raw_reply = call_ai(
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
        llm_action = parse_llm_response_action(llm_raw_reply)
        if llm_action.kind == ActionKind.NO_REPLY:
            fallback_text = _build_explicit_trigger_no_reply_fallback(merged_text, batch, llm_action)
            if fallback_text:
                llm_action = ResponseAction(kind=ActionKind.TEXT, text=fallback_text, reason="explicit_no_reply_fallback")
            else:
                execute_group_action(
                    group_id,
                    llm_action,
                    target_message_id=None,
                    quiet=not should_log_group(group_id),
                )
                log(f"[GROUP_CHAT] llm_action=no_reply group_id={group_id} reason={llm_action.reason!r}")
                continue
        if llm_action.kind == ActionKind.REACTION:
            target_message_id = _pick_reaction_target_message_id(batch)
            action_result = execute_group_action(
                group_id,
                llm_action,
                target_message_id=target_message_id,
                quiet=not should_log_group(group_id),
            )
            if action_result.get("ok"):
                record_group_strategy_reply(group_id)
                log(
                    f"[GROUP_CHAT] llm_action=reaction group_id={group_id}"
                    f" message_id={target_message_id} applied_count={action_result.get('applied_count', 0)}"
                )
                continue
        code_file_result = _maybe_send_generated_code_file(
            group_id,
            merged_text,
            llm_action.text,
            reply_to_message_id=_pick_text_reply_target_message_id(batch, llm_action.text),
            quiet=not should_log_group(group_id),
            log=log,
        )
        if code_file_result.get("handled"):
            append_group_chat_log(
                BASE_DATA_DIR,
                group_id,
                {
                    "timestamp": int(batch[-1].timestamp or 0) if batch else 0,
                    "sender_name": "群聊汇总",
                    "user_id": batch[-1].user_id if batch else None,
                    "message": merged_text,
                    "assistant": code_file_result.get("reply", ""),
                    "source": "group_chat:generated_file",
                },
                limit=500,
            )
            continue
        llm_action.text = _humanize_group_reply(llm_action.text, merged_text)
        delay_ms = int(strategy.get("delay_ms") or 0)
        if strategy.get("mode") == "delay_text" and delay_ms > 0:
            log(f"[GROUP_CHAT] strategy_delay group_id={group_id} delay_ms={delay_ms}")
            time.sleep(delay_ms / 1000.0)
        requested_parts = _detect_requested_parts(batch[-1].text if batch else "")
        reply_to_message_id = _pick_text_reply_target_message_id(batch, llm_action.text)
        action_result = execute_group_action(
            group_id,
            llm_action,
            target_message_id=None,
            quiet=not should_log_group(group_id),
            force_parts=requested_parts,
            reply_to_message_id=reply_to_message_id,
        )
        if not action_result.get("ok"):
            log(
                f"[GROUP_CHAT] send_skipped_empty group_id={group_id}"
                f" reason={action_result.get('reason', 'send_failed')}"
                f" reply_to_message_id={reply_to_message_id or '-'}"
            )
            continue
        if action_result.get("ok"):
            record_group_strategy_reply(group_id)
        append_group_chat_log(
            BASE_DATA_DIR,
            group_id,
            {
                "timestamp": int(batch[-1].timestamp or 0) if batch else 0,
                "sender_name": "群聊汇总",
                "user_id": batch[-1].user_id if batch else None,
                "message": merged_text,
                "assistant": llm_action.text,
                "source": "group_chat",
            },
            limit=500,
        )
        log(
            f"[GROUP_CHAT] replied group_id={group_id}"
            f" merged_message_count={merged_count}"
            f" merged_user_count={user_count}"
            f" requested_parts={requested_parts or 1}"
            f" reply_to_message_id={reply_to_message_id or '-'}"
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


def _pick_batch_trace_id(messages: list[PendingGroupMessage]) -> str:
    for item in reversed(messages or []):
        if item.trace_id:
            return item.trace_id
    return ""


def _pick_batch_strategy(messages: list[PendingGroupMessage]) -> dict:
    for item in reversed(messages or []):
        if isinstance(item.strategy, dict):
            return item.strategy
    return {}


def _context_window_ms(strategy_cfg: dict) -> int:
    if GROUP_DEBOUNCE_MS != _DEFAULT_GROUP_DEBOUNCE_MS:
        return max(0, int(GROUP_DEBOUNCE_MS))
    return max(0, int(strategy_cfg.get("context_window_sec") or 5) * 1000)


def _should_flush_head_message_now(messages: list[PendingGroupMessage]) -> bool:
    if not messages:
        return False
    return _looks_like_forwarded_chat_record(messages[0].text)


def _select_group_batch_size(messages: list[PendingGroupMessage]) -> int:
    if not messages:
        return 0
    if _looks_like_multi_user_request_batch(messages):
        return 1
    first = messages[0]
    size = 1
    for item in messages[1:]:
        if _should_split_before_message(first, item):
            break
        size += 1
    return size


def _looks_like_multi_user_request_batch(messages: list[PendingGroupMessage]) -> bool:
    if len(messages) < 2:
        return False
    request_count = 0
    request_user_ids: set[str] = set()
    for item in messages:
        if item.explicit_trigger or _looks_like_action_or_question_request(item.text):
            request_count += 1
            request_user_ids.add(str(item.user_id))
    return request_count >= 2 and len(request_user_ids) >= 2


def _should_split_before_message(first: PendingGroupMessage, item: PendingGroupMessage) -> bool:
    if item.user_id == first.user_id:
        return False
    if item.explicit_trigger or first.explicit_trigger:
        return True
    if _looks_like_action_or_question_request(item.text) or _looks_like_action_or_question_request(first.text):
        return True
    return False


def _looks_like_action_or_question_request(text: str) -> bool:
    normalized = normalize_query_text(text)
    if not normalized:
        return False
    if any(token in normalized for token in ("?", "？", "吗", "怎么", "为什么", "咋")):
        return True
    return any(
        token in normalized
        for token in (
            "帮我",
            "发过来",
            "列出",
            "发送",
            "关闭",
            "删除",
            "删掉",
            "格式化",
            "写个",
            "写一个",
            "生成",
            "打开",
            "下载",
        )
    )


def _compute_turn_extension_ms(
    messages: list[PendingGroupMessage],
    debounce_started_monotonic: float,
    *,
    max_window_seconds: int = _TURN_EXTENSION_MAX_WINDOW_SECONDS,
) -> int:
    if len(messages) < 2 or not debounce_started_monotonic:
        return 0
    elapsed = time.monotonic() - debounce_started_monotonic
    if elapsed >= max(1, int(max_window_seconds)):
        return 0
    latest = messages[-1]
    previous = messages[-2]
    if latest.user_id is None or latest.user_id != previous.user_id:
        return 0
    latest_text = normalize_query_text(latest.text)
    previous_text = normalize_query_text(previous.text)
    if not latest_text or not previous_text:
        return 0
    if latest.explicit_trigger or previous.explicit_trigger or _looks_like_followup_text(latest_text):
        return int(_TURN_EXTENSION_SECONDS * 1000)
    return 0


def _looks_like_followup_text(text: str) -> bool:
    normalized = normalize_query_text(text)
    if not normalized:
        return False
    if len(normalized) <= 18:
        return True
    return any(token in normalized for token in ("还有", "然后", "补充", "刚才", "上面", "这个", "那个", "的话", "所以"))


def _build_group_safety_action(merged_text: str) -> ResponseAction | None:
    text = normalize_query_text(merged_text)
    if not text:
        return None
    if _is_dangerous_file_or_secret_request(text):
        return ResponseAction(kind=ActionKind.TEXT, text="不行，这个会碰本机文件/密钥。", reason="dangerous_file_request")
    if _is_heavy_code_request(text):
        return ResponseAction(kind=ActionKind.TEXT, text="这个量太大了，群里不接重活。拆小点再说。", reason="heavy_code_request")
    return None


def _is_dangerous_file_or_secret_request(text: str) -> bool:
    normalized = normalize_query_text(text)
    if not normalized:
        return False
    if _DANGEROUS_FILE_REQUEST_PATTERN.search(normalized):
        return True
    return any(token in normalized.lower() for token in ("api_key", "apikey", "access_token", "secret_key"))


def _is_heavy_code_request(text: str) -> bool:
    normalized = normalize_query_text(text)
    if not _CODE_REQUEST_PATTERN.search(normalized):
        return False
    for match in _HEAVY_CODE_REQUEST_PATTERN.finditer(normalized):
        try:
            if int(match.group(1)) >= 100:
                return True
        except Exception:
            continue
    return any(token in normalized for token in ("大型项目", "完整项目", "全套", "一整个项目", "100行以上", "上百行"))


def _maybe_send_generated_code_file(
    group_id,
    user_text: str,
    reply_text: str,
    *,
    reply_to_message_id: int | None,
    quiet: bool,
    log,
) -> dict:
    if not _should_send_reply_as_code_file(user_text, reply_text):
        return {"handled": False}
    artifact = _build_generated_code_artifact(group_id, user_text, reply_text)
    if not artifact:
        return {"handled": False}
    file_result = send_group_file(group_id, artifact["path"], name=artifact["name"], quiet=quiet)
    if not file_result.get("ok"):
        log(
            f"[GROUP_CHAT] generated_file_failed group_id={group_id}"
            f" file={artifact['path']!r} reason={file_result.get('reason') or file_result.get('error')}"
        )
        return {"handled": False}
    notice = f"写好了，直接发文件了：{artifact['name']}"
    execute_group_action(
        group_id,
        ResponseAction(kind=ActionKind.TEXT, text=notice, reason="generated_code_file"),
        target_message_id=None,
        quiet=quiet,
        reply_to_message_id=reply_to_message_id,
    )
    log(f"[GROUP_CHAT] generated_file_sent group_id={group_id} file={artifact['path']!r}")
    return {"handled": True, "reply": notice, "file": artifact["path"], "name": artifact["name"]}


def _should_send_reply_as_code_file(user_text: str, reply_text: str) -> bool:
    request_text = normalize_query_text(user_text)
    reply = str(reply_text or "")
    if not request_text or not reply:
        return False
    if not _CODE_REQUEST_PATTERN.search(request_text):
        return False
    return bool(_CODE_BLOCK_PATTERN.search(reply) or _CODE_LIKE_PATTERN.search(reply) or len(reply) >= 500)


def _build_generated_code_artifact(group_id, user_text: str, reply_text: str) -> dict | None:
    content, language = _extract_generated_code_content(reply_text)
    content = content.strip()
    if not content:
        return None
    os.makedirs(GENERATED_GROUP_FILE_DIR, exist_ok=True)
    extension = _code_language_extension(language, user_text, content)
    timestamp = int(time.time())
    name = f"qq_generated_{group_id}_{timestamp}{extension}"
    path = os.path.abspath(os.path.join(GENERATED_GROUP_FILE_DIR, name))
    safe_root = os.path.abspath(GENERATED_GROUP_FILE_DIR)
    if os.path.commonpath([safe_root, path]) != safe_root:
        return None
    with open(path, "w", encoding="utf-8") as file_obj:
        file_obj.write(content)
        if not content.endswith("\n"):
            file_obj.write("\n")
    return {"path": path, "name": name}


def _extract_generated_code_content(reply_text: str) -> tuple[str, str]:
    blocks = _CODE_BLOCK_PATTERN.findall(str(reply_text or ""))
    if not blocks:
        return str(reply_text or ""), ""
    language, code = max(blocks, key=lambda item: len(item[1]))
    return code, str(language or "").strip().lower()


def _code_language_extension(language: str, user_text: str, content: str) -> str:
    lang = (language or "").lower()
    text = f"{user_text}\n{content}".lower()
    mapping = {
        "python": ".py",
        "py": ".py",
        "javascript": ".js",
        "js": ".js",
        "typescript": ".ts",
        "ts": ".ts",
        "html": ".html",
        "css": ".css",
        "java": ".java",
        "c": ".c",
        "cpp": ".cpp",
        "c++": ".cpp",
        "go": ".go",
        "rust": ".rs",
        "rs": ".rs",
        "bash": ".sh",
        "shell": ".sh",
        "sh": ".sh",
    }
    if lang in mapping:
        return mapping[lang]
    if "<!doctype" in text or "<html" in text:
        return ".html"
    if "python" in text or "def " in text or "import " in text:
        return ".py"
    if "javascript" in text or "function " in text or "const " in text:
        return ".js"
    return ".txt"


def _detect_repeat_follow_text(group_id, messages: list[PendingGroupMessage]) -> tuple[str, int]:
    counts: dict[str, int] = {}
    first_seen_order: list[str] = []
    for _timestamp, text in _recent_repeat_messages_for_group(group_id):
        if text not in counts:
            first_seen_order.append(text)
            counts[text] = 0
        counts[text] += 1
    for item in messages:
        text = normalize_query_text(item.text)
        if not _is_safe_repeat_follow_text(text):
            continue
        if text not in counts:
            first_seen_order.append(text)
            counts[text] = 0
        counts[text] += 1
        if counts[text] >= _REPEAT_FOLLOW_MIN_COUNT:
            _record_repeat_messages(group_id, messages)
            return text, counts[text]

    for text in first_seen_order:
        count = counts.get(text, 0)
        if count >= _REPEAT_FOLLOW_MIN_COUNT:
            _record_repeat_messages(group_id, messages)
            return text, count
    _record_repeat_messages(group_id, messages)
    return "", 0


def _recent_repeat_messages_for_group(group_id, *, now: float | None = None) -> list[tuple[float, str]]:
    current = time.monotonic() if now is None else now
    key = str(group_id)
    recent = [
        (timestamp, text)
        for timestamp, text in _RECENT_REPEAT_MESSAGES.get(key, [])
        if current - timestamp <= _REPEAT_FOLLOW_WINDOW_SECONDS
    ]
    _RECENT_REPEAT_MESSAGES[key] = recent
    return recent


def _record_repeat_messages(group_id, messages: list[PendingGroupMessage], *, now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    key = str(group_id)
    recent = _recent_repeat_messages_for_group(group_id, now=current)
    for item in messages:
        text = normalize_query_text(item.text)
        if _is_safe_repeat_follow_text(text):
            recent.append((current, text))
    _RECENT_REPEAT_MESSAGES[key] = recent[-50:]


def _is_safe_repeat_follow_text(text: str) -> bool:
    normalized = normalize_query_text(text)
    if not normalized:
        return False
    if len(normalized) > _REPEAT_FOLLOW_MAX_CHARS:
        return False
    if "[CQ:" in normalized or "[[" in normalized or "]]" in normalized:
        return False
    if _looks_like_forwarded_chat_record(normalized):
        return False
    return True


def _claim_repeat_follow(group_id, text: str, *, now: float | None = None) -> bool:
    normalized = normalize_query_text(text)
    if not _is_safe_repeat_follow_text(normalized):
        return False
    current = time.monotonic() if now is None else now
    _prune_repeat_follow_cache(current)
    key = f"{group_id}:{hashlib.md5(normalized.encode('utf-8')).hexdigest()}"
    last_followed = _RECENT_REPEAT_FOLLOWS.get(key)
    if last_followed is not None and current - last_followed < _REPEAT_FOLLOW_COOLDOWN_SECONDS:
        return False
    _RECENT_REPEAT_FOLLOWS[key] = current
    return True


def _prune_repeat_follow_cache(now: float) -> None:
    expired = [
        key
        for key, timestamp in _RECENT_REPEAT_FOLLOWS.items()
        if now - timestamp >= _REPEAT_FOLLOW_COOLDOWN_SECONDS * 2
    ]
    for key in expired:
        _RECENT_REPEAT_FOLLOWS.pop(key, None)


def _detect_requested_parts(text: str) -> int | None:
    normalized = normalize_query_text(text)
    if not normalized:
        return None
    if not any(keyword in normalized for keyword in ("发", "分", "条", "消息", "回复")):
        return None

    match = re.search(r"([0-9一二两三四五六七八九十]+)\s*条(?:消息|回复)?", normalized)
    if not match:
        return None
    raw_num = match.group(1)
    if raw_num.isdigit():
        value = int(raw_num)
    else:
        value = _ZH_NUM_MAP.get(raw_num, 0)
        if value == 0 and raw_num.startswith("十"):
            value = 10 + _ZH_NUM_MAP.get(raw_num[1:], 0)
        elif value == 0 and raw_num.endswith("十"):
            value = _ZH_NUM_MAP.get(raw_num[0], 1) * 10
    if value < 2:
        return None
    return min(value, 5)


def _detect_direct_reaction_request_count(text: str) -> int:
    normalized = normalize_query_text(text)
    if not normalized:
        return 0
    if not any(token in normalized for token in ("消息", "这条", "上面", "它", "那条", "刚才", "上一条", "react")):
        return 0
    asks_react = any(token in normalized for token in ("贴", "点", "按", "react"))
    has_emoji_word = (
        ("表情" in normalized)
        or ("emoji" in normalized)
        or ("react" in normalized)
        or ("按钮" in normalized)
        or ("红心" in normalized)
        or ("爱心" in normalized)
        or ("不一样" in normalized)
        or ("换一个" in normalized)
    )
    if not (asks_react and has_emoji_word):
        return 0

    # "贴几个/贴2个/贴三次" -> allow up to 3 to avoid spam.
    m = re.search(r"(几|[0-9一二两三四五])\s*(个|次)?", normalized)
    if not m:
        return 1
    raw = m.group(1)
    if raw == "几":
        return 2
    if raw.isdigit():
        return min(max(int(raw), 1), 3)
    value = _ZH_NUM_MAP.get(raw, 1)
    return min(max(value, 1), 3)


def _get_reaction_decision_mode(group_config: dict | None) -> str:
    cfg = group_config or {}
    mode = str(cfg.get("reaction_decision_mode", "llm_first") or "llm_first").strip().lower()
    if mode not in {"llm_first", "rule_first", "hybrid"}:
        return "llm_first"
    return mode


def _humanize_group_reply(reply: str, merged_text: str) -> str:
    """Reduce repetitive meme fillers so replies sound less mechanical."""
    normalized = normalize_query_text(reply)
    if not normalized:
        return "行"

    normalized = _REPLY_FILLER_PATTERN.sub(lambda m: f" {m.group(1)}", normalized).strip()
    if normalized.startswith("确实 "):
        normalized = normalized[3:].strip() or "行"
    if normalized.startswith("草 "):
        normalized = normalized[2:].strip() or "离谱"

    if _looks_like_clarifying_type_question(normalized) and not _looks_like_user_asked_type_choice(merged_text):
        return "发啥都行，我看着接。"

    friendly_reply = _humanize_friendly_greeting_reply(normalized, merged_text)
    if friendly_reply:
        return friendly_reply

    if _REPLY_LOOP_PATTERN.fullmatch(normalized):
        return _build_context_fallback(merged_text)
    normalized = _soften_plain_group_answer(normalized, merged_text)
    return normalized


def _soften_plain_group_answer(reply: str, merged_text: str) -> str:
    normalized = normalize_query_text(reply)
    if not _looks_like_plain_answer(normalized, merged_text):
        return normalized
    if any(token in normalized for token in ("喵", "呀", "捏", "欸", "草", "笑死", "离谱")):
        return normalized
    if len(normalized) <= 18:
        return normalized.rstrip("。！？!? ") + "喵"
    return normalized.rstrip("。！？!? ") + "，大概是这样喵。"


def _humanize_friendly_greeting_reply(reply: str, merged_text: str) -> str | None:
    text = normalize_query_text(merged_text)
    if reply not in {"在", "嗯", "哦", "啊", "来了", "在呢"}:
        return None
    if any(token in text for token in ("宝宝", "宝贝", "亲亲", "老婆", "猫猫", "喵喵")):
        for token in ("宝宝", "宝贝", "亲亲", "老婆", "猫猫", "喵喵"):
            if token in text:
                return token
    if any(token in text for token in ("在吗", "在嘛", "在不", "喂", "醒醒")):
        return "在喵"
    return None


def _looks_like_plain_answer(reply: str, merged_text: str) -> bool:
    normalized_reply = normalize_query_text(reply)
    normalized_query = normalize_query_text(merged_text)
    if not normalized_reply or len(normalized_reply) > 80:
        return False
    if any(token in normalized_query for token in ("草", "妈", "操", "鸡巴", "几把", "色情", "政治", "敏感")):
        return False
    if any(token in normalized_reply for token in ("不能", "不要", "抱歉", "违法", "危险")):
        return False
    if "，" in normalized_reply or "。" in normalized_reply or any(token in normalized_reply for token in ("是", "不是", "适合", "更好", "因为", "没有")):
        return True
    return False


def _looks_like_clarifying_type_question(reply: str) -> bool:
    normalized = normalize_query_text(reply)
    return bool(
        normalized.endswith(("？", "?"))
        and "类型" in normalized
        and any(token in normalized for token in ("文字", "图片", "表情", "发什么", "哪种"))
    )


def _looks_like_user_asked_type_choice(text: str) -> bool:
    normalized = normalize_query_text(text)
    return any(token in normalized for token in ("何类型", "何意味", "何类型喵"))


def _build_context_fallback(merged_text: str) -> str:
    text = normalize_query_text(merged_text)
    if any(token in text for token in ("?", "？", "吗", "咋", "怎么")):
        return "何意味"
    if any(token in text for token in ("图", "图片", "截图", "看这个")):
        return "我看到了"
    return "收到"


def _build_explicit_trigger_no_reply_fallback(
    merged_text: str,
    batch: list[PendingGroupMessage],
    action: ResponseAction,
) -> str | None:
    text = normalize_query_text(merged_text)
    if not text or not any(bool(item.explicit_trigger) for item in batch):
        return None
    if _looks_like_stop_talking_request(text):
        return None
    if action.reason == "legacy_emoji_tag_blocked":
        return None
    if any(token in text for token in ("宝宝", "在吗", "在不", "醒醒", "喂")):
        return "在呢喵"
    if any(token in text for token in ("?", "？", "吗", "怎么", "咋", "为什么")):
        return "喵"
    return _build_context_fallback(text)


def _pick_reaction_target_message_id(messages: list[PendingGroupMessage]) -> int | None:
    for item in reversed(messages):
        if item.message_id:
            try:
                return int(item.message_id)
            except (TypeError, ValueError):
                continue
    return None


def _pick_text_reply_target_message_id(messages: list[PendingGroupMessage], reply_text: str = "") -> int | None:
    if not messages:
        return None
    reply = normalize_query_text(reply_text)
    scored: list[tuple[int, int, int]] = []
    for index, item in enumerate(messages):
        if not item.message_id:
            continue
        text = normalize_query_text(item.text)
        score = index
        if "?" in text or "？" in text or any(token in text for token in ("吗", "怎么", "为什么", "啥", "什么")):
            score += 1000
        if item.explicit_trigger:
            score += 500
        if _reply_mentions_message_topic(reply, text):
            score += 800
        try:
            scored.append((score, index, int(item.message_id)))
        except (TypeError, ValueError):
            continue
    if not scored:
        return None
    return max(scored)[2]


def _reply_mentions_message_topic(reply_text: str, message_text: str) -> bool:
    reply = normalize_query_text(reply_text).lower()
    message = normalize_query_text(message_text).lower()
    if not reply or not message:
        return False
    keywords = [
        token
        for token in re.split(r"[\s，。！？,.!?:：；、/|]+", message)
        if len(token) >= 2 and token not in {"这个", "那个", "什么", "怎么", "为什么"}
    ]
    return any(token in reply for token in keywords[:8])


def _is_global_listen_group(group_id, group_config: dict | None) -> bool:
    cfg = group_config or {}
    return bool(cfg.get("reply_all_messages", False)) or int(group_id or 0) in GLOBAL_LISTEN_GROUP_IDS


def _decide_group_response_mode_with_llm(
    merged_text: str,
    batch: list[PendingGroupMessage],
    group_config: dict | None,
    log,
) -> dict:
    normalized_text = normalize_query_text(merged_text)
    if not normalized_text:
        return {"mode": "silence", "reason": "empty_text"}

    mentions_bot = any(bool(item.explicit_trigger) for item in batch)
    has_question = any(token in normalized_text for token in ("?", "？", "怎么", "为什么", "吗", "咋"))
    message_count = len(batch)
    if _should_allow_ambient_chatter_interjection(batch, normalized_text, mentions_bot=mentions_bot):
        return {"mode": "text", "reason": "ambient_chatter_interjection"}
    if _looks_like_forwarded_chat_record(normalized_text):
        return {"mode": "text", "reason": "forwarded_chat_record"}
    local_reaction_reason = _local_global_reaction_reason(normalized_text, mentions_bot=mentions_bot)
    if local_reaction_reason:
        decision = {"mode": "reaction", "reason": local_reaction_reason}
        log(
            f"[GROUP_CHAT] llm_mode_decision mode={decision['mode']}"
            f" reason={decision.get('reason', '')!r}"
            f" mentions_bot={mentions_bot} source=local_reaction_hint"
        )
        return decision
    if _should_silence_trivial_global_message(normalized_text, mentions_bot=mentions_bot):
        return {"mode": "silence", "reason": "trivial_global_message"}

    reaction_bias = 0.24 if not mentions_bot else 0.18
    reaction_bias = max(0.0, min(0.95, reaction_bias))

    prompt = (
        "你是群聊响应决策器，只输出 JSON，不要解释。\n"
        "任务：从 silence/reaction/text 三选一。\n"
        "规则：\n"
        "1) 低信息熵、闲聊噪音、明显不是对机器人说话 -> silence。\n"
        "2) 明确提问、求助、点名机器人 -> text。\n"
        "3) reaction 只用于明确适合轻互动的消息；不要每条都贴。\n"
        "4) 输出 JSON: {\"mode\":\"silence|reaction|text\",\"reason\":\"<=20字\"}\n"
        f"上下文摘要: message_count={message_count}, mentions_bot={mentions_bot}, has_question={has_question},"
        f" reaction_bias={reaction_bias}\n"
        f"群消息:\n{normalized_text}"
    )
    raw = call_ai(
        prompt,
        metadata={
            "user_id": "group_mode_selector",
            "prompt_mode": "group_response_mode",
            "query_len": len(normalized_text),
        },
    )
    decision = _parse_group_response_mode(raw)
    if mentions_bot and decision["mode"] == "silence" and not _looks_like_stop_talking_request(normalized_text):
        decision = {"mode": "text", "reason": "explicit_trigger_override"}
    if decision["mode"] == "reaction" and _should_silence_trivial_global_message(normalized_text, mentions_bot=mentions_bot):
        decision = {"mode": "silence", "reason": "local_trivial_override"}
    log(
        f"[GROUP_CHAT] llm_mode_decision mode={decision['mode']}"
        f" reason={decision.get('reason', '')!r}"
        f" mentions_bot={mentions_bot}"
    )
    return decision


def _looks_like_stop_talking_request(text: str) -> bool:
    normalized = normalize_query_text(text)
    return any(token in normalized for token in ("别多嘴", "闭嘴", "别说话", "别回", "不要回", "少说", "安静", "别插嘴"))


def _looks_like_forwarded_chat_record(text: str) -> bool:
    normalized = normalize_query_text(text)
    return "[聊天记录]" in normalized or "聊天记录" in normalized or "合并转发" in normalized


def _should_allow_ambient_chatter_interjection(
    batch: list[PendingGroupMessage],
    merged_text: str,
    *,
    mentions_bot: bool,
) -> bool:
    if mentions_bot:
        return False
    if len(batch) < _AMBIENT_CHATTER_REPLY_THRESHOLD:
        return False
    text = normalize_query_text(merged_text)
    if not text:
        return False
    if _should_silence_trivial_global_message(text, mentions_bot=False):
        return False
    return True


def _local_global_reaction_reason(text: str, *, mentions_bot: bool) -> str:
    normalized = normalize_query_text(text)
    if not normalized or mentions_bot:
        return ""
    if any(token in normalized for token in ("想摸", "想舔", "想冲", "冲了", "擦边", "涩", "色", "骚", "烧", "老婆睡", "大果睡")):
        return "sexual_reaction_hint"
    if any(token in normalized for token in ("睡觉了", "晚安", "睡了", "困了", "先睡")):
        return "goodnight_reaction_hint"
    return ""


def _should_silence_trivial_global_message(text: str, *, mentions_bot: bool) -> bool:
    normalized = normalize_query_text(text)
    if not normalized or mentions_bot:
        return False
    if any(token in normalized for token in ("?", "？", "吗", "怎么", "为什么", "咋", "谁", "哪", "啥")):
        return False
    if any(token in normalized for token in ("贴", "表情", "emoji", "react", "按钮", "红心", "舔屏")):
        return False
    if len(normalized) <= 8:
        return True
    trivial_tokens = ("哈哈", "笑死", "笑了", "草", "绷", "666", "确实", "害怕", "击败", "离谱")
    return any(token in normalized for token in trivial_tokens) and len(normalized) <= 14


def _parse_group_response_mode(raw) -> dict:
    text = str(raw or "").strip()
    if not text:
        return {"mode": "silence", "reason": "empty_llm_output"}
    candidate = text
    if "{" in text and "}" in text:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            candidate = text[start : end + 1]
    mode = ""
    reason = ""
    try:
        obj = json.loads(candidate)
        mode = str(obj.get("mode", "")).strip().lower()
        reason = str(obj.get("reason", "")).strip()
    except Exception:
        lowered = text.lower()
        if "silence" in lowered:
            mode = "silence"
        elif "text" in lowered:
            mode = "text"
        elif "reaction" in lowered:
            mode = "reaction"
    if mode not in {"silence", "reaction", "text"}:
        return {"mode": "silence", "reason": "invalid_mode_fallback"}
    return {"mode": mode, "reason": reason[:20]}


def _extract_emoji_tag(reply: str) -> str | None:
    normalized = normalize_query_text(reply)
    if not normalized:
        return None
    m = re.fullmatch(r"\[emoji:([a-zA-Z0-9_/\u4e00-\u9fa5]+)\]", normalized.strip())
    if not m:
        return None
    return str(m.group(1)).strip().lower()


def _should_use_reaction_instead(merged_text: str, reply: str, group_config: dict | None = None) -> bool:
    text = normalize_query_text(merged_text)
    generated = normalize_query_text(reply)
    cfg = group_config or {}
    if "[[NO_REPLY]]" in str(reply or ""):
        return True
    if not text:
        return False
    if any(token in text for token in ("?", "？", "吗", "怎么", "为何", "为什么", "求")):
        return False
    if len(text) >= 40:
        return False
    low_value_text = bool(re.fullmatch(r"[\W_]*", text)) or text in {"6", "66", "666", "草", "?", "？", "哈哈", "ok", "收到"}
    low_value_reply = generated in {"收到", "懂你意思", "爸爸", "神了", "666", "何意味"}
    if low_value_text or low_value_reply:
        return True

    # Moonlark-like social reaction behavior:
    # for short casual messages, occasionally react instead of sending text.
    decision_mode = _get_reaction_decision_mode(cfg)
    if decision_mode == "rule_first" and len(text) <= 14:
        rate = 0.45 if bool(cfg.get("reply_all_messages", False)) else 0.32
        bucket = int(hashlib.md5(text.encode("utf-8")).hexdigest()[:4], 16) / 0xFFFF
        return bucket < rate

    if decision_mode == "hybrid" and len(text) <= 12:
        rate = 0.28
        if bool(cfg.get("reply_all_messages", False)):
            rate += 0.2
        rate = max(0.0, min(0.9, float(rate)))
        bucket = int(hashlib.md5(text.encode("utf-8")).hexdigest()[:4], 16) / 0xFFFF
        if bucket < rate:
            return True
    return False
