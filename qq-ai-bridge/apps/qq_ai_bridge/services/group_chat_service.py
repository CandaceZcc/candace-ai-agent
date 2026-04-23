"""Group chat orchestration helpers."""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass, field
import re

from shared.ai.llm_client import call_ai
from storage_utils import append_group_chat_log
from storage_utils import load_group_config as load_group_config_from_file

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text
from apps.qq_ai_bridge.adapters.napcat_client import react_message_with_preferred_emojis, send_group_msg
from apps.qq_ai_bridge.config.settings import GROUP_CONFIG_PATH
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR
from apps.qq_ai_bridge.config.settings import GLOBAL_LISTEN_GROUP_IDS
from apps.qq_ai_bridge.services.expression_selector import select_group_expression
from apps.qq_ai_bridge.services.prompt_service import prepare_group_ai_prompt
from apps.qq_ai_bridge.services.timing_gate import evaluate_group_timing_gate

GROUP_DEBOUNCE_MS = 5000


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
_REPLY_FILLER_PATTERN = re.compile(r"(?:^|\s)(确实|草|牛逼|典|寄了?|救命|贴贴)(?:\s+\1)+", re.IGNORECASE)
_REPLY_LOOP_PATTERN = re.compile(r"^(确实|草|牛逼|典|寄了?|救命|贴贴)(\s+(确实|草|牛逼|典|寄了?|救命|贴贴))*$", re.IGNORECASE)


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
        reply_reference=reply_reference if isinstance(reply_reference, dict) else None,
        explicit_trigger=bool(explicit_trigger),
    )

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

        direct_react_count = _detect_direct_reaction_request_count(merged_text)
        decision_mode = _get_reaction_decision_mode(group_config)
        if direct_react_count > 0 and decision_mode in {"rule_first", "hybrid", "llm_first"}:
            target_message_id = _pick_reaction_target_message_id(batch)
            if target_message_id:
                reacted = 0
                for _ in range(direct_react_count):
                    reaction_result = react_message_with_preferred_emojis(
                        target_message_id,
                        quiet=not should_log_group(group_id),
                    )
                    if not reaction_result.get("ok"):
                        break
                    reacted += 1
                    time.sleep(0.12)
                if reacted > 0:
                    log(
                        f"[GROUP_CHAT] direct_reacted group_id={group_id} "
                        f"message_id={target_message_id} count={reacted}"
                    )
                    continue

        timing_decision = evaluate_group_timing_gate(group_id, batch, group_config)
        if timing_decision:
            if timing_decision.mode.value == "no_reply":
                log(
                    f"[GROUP_CHAT] timing_gate_skip group_id={group_id} "
                    f"reason={timing_decision.reason} confidence={timing_decision.confidence}"
                )
                continue
            if timing_decision.mode.value == "reaction":
                target_message_id = _pick_reaction_target_message_id(batch)
                if target_message_id:
                    reaction_result = react_message_with_preferred_emojis(
                        target_message_id,
                        quiet=not should_log_group(group_id),
                    )
                    if reaction_result.get("ok"):
                        log(
                            f"[GROUP_CHAT] timing_gate_reacted group_id={group_id} "
                            f"message_id={target_message_id} reason={timing_decision.reason}"
                        )
                        continue
            if timing_decision.mode.value == "text" and timing_decision.text:
                send_group_msg(
                    group_id,
                    timing_decision.text,
                    quiet=not should_log_group(group_id),
                    reply_to_message_id=_pick_reply_target_message_id(batch),
                )
                append_group_chat_log(
                    BASE_DATA_DIR,
                    group_id,
                    {
                        "timestamp": int(batch[-1].timestamp or 0) if batch else 0,
                        "sender_name": "群聊时机门控",
                        "user_id": batch[-1].user_id if batch else None,
                        "message": merged_text,
                        "assistant": timing_decision.text,
                        "source": "timing_gate",
                    },
                    limit=500,
                )
                log(
                    f"[GROUP_CHAT] timing_gate_replied group_id={group_id} "
                    f"reason={timing_decision.reason} text={timing_decision.text!r}"
                )
                continue

        prompt_payload = prepare_group_ai_prompt(
            group_id,
            merged_text,
            user_id=batch[-1].user_id if batch else None,
            log=log,
            batch_context=merged_batch,
            group_config=group_config,
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
        reply = _humanize_group_reply(reply, merged_text)
        reply = select_group_expression(reply, merged_text, group_config=group_config)
        requested_parts = _detect_requested_parts(batch[-1].text if batch else "")
        if _should_use_reaction_instead(merged_text, reply, group_config=group_config):
            target_message_id = _pick_reaction_target_message_id(batch)
            if target_message_id:
                reaction_result = react_message_with_preferred_emojis(
                    target_message_id,
                    quiet=not should_log_group(group_id),
                )
                if reaction_result.get("ok"):
                    log(
                        f"[GROUP_CHAT] reacted group_id={group_id} message_id={target_message_id} "
                        f"emoji={reaction_result.get('emoji_name')} id={reaction_result.get('emoji_id')}"
                    )
                    continue
        send_group_msg(
            group_id,
            reply,
            quiet=not should_log_group(group_id),
            force_parts=requested_parts,
            reply_to_message_id=_pick_reply_target_message_id(batch),
        )
        append_group_chat_log(
            BASE_DATA_DIR,
            group_id,
            {
                "timestamp": int(batch[-1].timestamp or 0) if batch else 0,
                "sender_name": "群聊汇总",
                "user_id": batch[-1].user_id if batch else None,
                "message": merged_text,
                "assistant": reply,
                "source": "group_chat",
            },
            limit=500,
        )
        log(
            f"[GROUP_CHAT] replied group_id={group_id}"
            f" merged_message_count={merged_count}"
            f" merged_user_count={user_count}"
            f" requested_parts={requested_parts or 1}"
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
    reply_references: list[dict] = []

    for item in messages:
        text = normalize_query_text(item.text)
        if not text:
            continue
        raw_messages += 1
        if item.reply_reference:
            reply_references.append(item.reply_reference)
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
        "reply_references": reply_references,
    }


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
    asks_react = any(token in normalized for token in ("贴", "发", "react", "emoji"))
    has_emoji_word = ("表情" in normalized) or ("emoji" in normalized) or ("react" in normalized)
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

    if _REPLY_LOOP_PATTERN.fullmatch(normalized):
        return _build_context_fallback(merged_text)
    return normalized


def _build_context_fallback(merged_text: str) -> str:
    text = normalize_query_text(merged_text)
    if any(token in text for token in ("?", "？", "吗", "咋", "怎么")):
        return "有点离谱"
    if any(token in text for token in ("图", "图片", "截图", "看这个")):
        return "我看到了"
    return "收到"


def _pick_reaction_target_message_id(messages: list[PendingGroupMessage]) -> int | None:
    for item in reversed(messages):
        if item.message_id:
            try:
                return int(item.message_id)
            except (TypeError, ValueError):
                continue
    return None


def _pick_reply_target_message_id(messages: list[PendingGroupMessage]) -> int | None:
    return _pick_reaction_target_message_id(messages)


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
    low_value_reply = generated in {"收到", "行", "嗯", "哈哈", "有点离谱", "我看到了"}
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
