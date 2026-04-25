"""Group chat orchestration helpers."""

from __future__ import annotations

import json
import hashlib
import threading
import time
from dataclasses import dataclass, field
import re

from shared.ai.llm_client import call_ai
from storage_utils import append_group_chat_log
from storage_utils import load_group_config as load_group_config_from_file

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text
from apps.qq_ai_bridge.config.settings import GROUP_CONFIG_PATH
from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR
from apps.qq_ai_bridge.config.settings import GLOBAL_LISTEN_GROUP_IDS
from apps.qq_ai_bridge.services.emoji_service import infer_reaction_preferred_order
from apps.qq_ai_bridge.services.prompt_service import prepare_group_ai_prompt
from apps.qq_ai_bridge.services.response_action import (
    ActionKind,
    ResponseAction,
    execute_group_action,
    parse_llm_response_action,
)

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
_RECENT_REPEAT_FOLLOWS: dict[str, float] = {}
_REPEAT_FOLLOW_COOLDOWN_SECONDS = 60
_REPEAT_FOLLOW_MIN_COUNT = 3
_REPEAT_FOLLOW_MAX_CHARS = 80
_TURN_EXTENSION_SECONDS = 2.0
_TURN_EXTENSION_MAX_WINDOW_SECONDS = 8.0
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


# load_group_config：加载群聊配置
def load_group_config(group_id) -> dict:
    """Load merged group config for a specific QQ group."""
    return load_group_config_from_file(GROUP_CONFIG_PATH, group_id)


# should_log_group：判断群聊日志开关
def should_log_group(group_id) -> bool:
    """Return whether logs should be printed for a group."""
    cfg = load_group_config(group_id)
    return not cfg.get("ignore", False) and not cfg.get("mute_log", False)


# enqueue_group_text：群聊文本入队合并
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
        reply_reference=reply_reference,
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


# _get_group_chat_state：获取群聊队列状态
def _get_group_chat_state(group_id) -> GroupChatState:
    key = str(group_id)
    with _GROUP_CHAT_STATES_LOCK:
        state = _GROUP_CHAT_STATES.get(key)
        if state is None:
            state = GroupChatState()
            _GROUP_CHAT_STATES[key] = state
        return state


# _run_group_chat_worker：运行群聊消费线程
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
            extension_ms = _compute_turn_extension_ms(state.pending, state.debounce_started_monotonic)
        if extension_ms > 0:
            time.sleep(extension_ms / 1000.0)
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

        repeat_text, repeat_count = _detect_repeat_follow_text(batch)
        if repeat_text and _claim_repeat_follow(group_id, repeat_text):
            action_result = execute_group_action(
                group_id,
                ResponseAction(kind=ActionKind.TEXT, text=repeat_text, reason="repeat_follow"),
                target_message_id=None,
                quiet=not should_log_group(group_id),
            )
            if action_result.get("ok"):
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
                    log(
                        f"[GROUP_CHAT] direct_reacted group_id={group_id} "
                        f"message_id={target_message_id} count={reacted}"
                    )
                    continue

        if global_listen_mode:
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
                log(
                    f"[GROUP_CHAT] llm_action=reaction group_id={group_id}"
                    f" message_id={target_message_id} applied_count={action_result.get('applied_count', 0)}"
                )
                continue
        llm_action.text = _humanize_group_reply(llm_action.text, merged_text)
        requested_parts = _detect_requested_parts(batch[-1].text if batch else "")
        reply_to_message_id = _pick_text_reply_target_message_id(batch, llm_action.text)
        execute_group_action(
            group_id,
            llm_action,
            target_message_id=None,
            quiet=not should_log_group(group_id),
            force_parts=requested_parts,
            reply_to_message_id=reply_to_message_id,
        )
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


# _merge_pending_group_messages：合并待处理群消息
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


# _compute_turn_extension_ms：计算补话等待时长
def _compute_turn_extension_ms(messages: list[PendingGroupMessage], debounce_started_monotonic: float) -> int:
    if len(messages) < 2 or not debounce_started_monotonic:
        return 0
    elapsed = time.monotonic() - debounce_started_monotonic
    if elapsed >= _TURN_EXTENSION_MAX_WINDOW_SECONDS:
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


# _looks_like_followup_text：判断是否补充发言
def _looks_like_followup_text(text: str) -> bool:
    normalized = normalize_query_text(text)
    if not normalized:
        return False
    if len(normalized) <= 18:
        return True
    return any(token in normalized for token in ("还有", "然后", "补充", "刚才", "上面", "这个", "那个", "的话", "所以"))


# _detect_repeat_follow_text：检测复读跟刷文本
def _detect_repeat_follow_text(messages: list[PendingGroupMessage]) -> tuple[str, int]:
    counts: dict[str, int] = {}
    first_seen_order: list[str] = []
    for item in messages:
        text = normalize_query_text(item.text)
        if not _is_safe_repeat_follow_text(text):
            continue
        if text not in counts:
            first_seen_order.append(text)
            counts[text] = 0
        counts[text] += 1
        if counts[text] >= _REPEAT_FOLLOW_MIN_COUNT:
            return text, counts[text]

    for text in first_seen_order:
        count = counts.get(text, 0)
        if count >= _REPEAT_FOLLOW_MIN_COUNT:
            return text, count
    return "", 0


# _is_safe_repeat_follow_text：校验复读文本安全
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


# _claim_repeat_follow：领取复读冷却名额
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


# _prune_repeat_follow_cache：清理复读冷却缓存
def _prune_repeat_follow_cache(now: float) -> None:
    expired = [
        key
        for key, timestamp in _RECENT_REPEAT_FOLLOWS.items()
        if now - timestamp >= _REPEAT_FOLLOW_COOLDOWN_SECONDS * 2
    ]
    for key in expired:
        _RECENT_REPEAT_FOLLOWS.pop(key, None)


# _detect_requested_parts：检测分条发送数量
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


# _detect_direct_reaction_request_count：检测直接贴表情请求
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


# _get_reaction_decision_mode：读取表情决策模式
def _get_reaction_decision_mode(group_config: dict | None) -> str:
    cfg = group_config or {}
    mode = str(cfg.get("reaction_decision_mode", "llm_first") or "llm_first").strip().lower()
    if mode not in {"llm_first", "rule_first", "hybrid"}:
        return "llm_first"
    return mode


# _humanize_group_reply：润色群聊回复语气
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


# _soften_plain_group_answer：群聊处理
def _soften_plain_group_answer(reply: str, merged_text: str) -> str:
    normalized = normalize_query_text(reply)
    if not _looks_like_plain_answer(normalized, merged_text):
        return normalized
    if any(token in normalized for token in ("喵", "呀", "捏", "欸", "草", "笑死", "离谱")):
        return normalized
    if len(normalized) <= 18:
        return normalized.rstrip("。！？!? ") + "喵"
    return normalized.rstrip("。！？!? ") + "，大概是这样喵。"


# _humanize_friendly_greeting_reply：回复处理
def _humanize_friendly_greeting_reply(reply: str, merged_text: str) -> str | None:
    text = normalize_query_text(merged_text)
    if reply not in {"在", "嗯", "哦", "啊", "来了", "在呢"}:
        return None
    if any(token in text for token in ("宝宝", "宝贝", "亲亲", "老婆", "猫猫", "喵喵")):
        for token in ("宝宝", "宝贝", "亲亲", "老婆", "猫猫", "喵喵"):
            if token in text:
                return token
    if any(token in text for token in ("在吗", "在嘛", "在不", "喂", "醒醒", "麦麦")):
        return "在喵"
    return None


# _looks_like_plain_answer：相关逻辑处理
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


# _looks_like_clarifying_type_question：相关逻辑处理
def _looks_like_clarifying_type_question(reply: str) -> bool:
    normalized = normalize_query_text(reply)
    return bool(
        normalized.endswith(("？", "?"))
        and "类型" in normalized
        and any(token in normalized for token in ("文字", "图片", "表情", "发什么", "哪种"))
    )


# _looks_like_user_asked_type_choice：用户处理
def _looks_like_user_asked_type_choice(text: str) -> bool:
    normalized = normalize_query_text(text)
    return any(token in normalized for token in ("什么类型", "哪种", "文字还是图片", "图片还是文字"))


# _build_context_fallback：构建上下文兜底
def _build_context_fallback(merged_text: str) -> str:
    text = normalize_query_text(merged_text)
    if any(token in text for token in ("?", "？", "吗", "咋", "怎么")):
        return "有点离谱"
    if any(token in text for token in ("图", "图片", "截图", "看这个")):
        return "我看到了"
    return "收到"


# _build_explicit_trigger_no_reply_fallback：构建回复兜底
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
        return "咋了"
    return _build_context_fallback(text)


# _pick_reaction_target_message_id：选择贴表情目标消息
def _pick_reaction_target_message_id(messages: list[PendingGroupMessage]) -> int | None:
    for item in reversed(messages):
        if item.message_id:
            try:
                return int(item.message_id)
            except (TypeError, ValueError):
                continue
    return None


# _pick_text_reply_target_message_id：选择文本回复引用目标
def _pick_text_reply_target_message_id(messages: list[PendingGroupMessage], reply_text: str = "") -> int | None:
    if not messages:
        return None
    reply = normalize_query_text(reply_text)
    scored: list[tuple[int, int, int]] = []
    for index, item in enumerate(messages):
        if not item.message_id:
            continue
        text = normalize_query_text(item.text)
        if not text:
            continue
        score = index
        if item.explicit_trigger:
            score += 1000
        if any(token in text for token in ("?", "？", "吗", "怎么", "为什么", "咋", "什么", "哪", "谁")):
            score += 200
        if any(token in text for token in ("图", "图片", "截图", "聊天记录", "这个", "上面", "刚才")):
            score += 120
        if reply and _reply_mentions_message_topic(reply, text):
            score += 80
        scored.append((score, index, int(item.message_id)))
    if not scored:
        return None
    return max(scored)[2]


# _reply_mentions_message_topic：回复消息处理
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


# _is_global_listen_group：判断是否全局监听群
def _is_global_listen_group(group_id, group_config: dict | None) -> bool:
    cfg = group_config or {}
    return bool(cfg.get("reply_all_messages", False)) or int(group_id or 0) in GLOBAL_LISTEN_GROUP_IDS


# _decide_group_response_mode_with_llm：调用模型决定回复模式
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


# _looks_like_stop_talking_request：请求相关逻辑
def _looks_like_stop_talking_request(text: str) -> bool:
    normalized = normalize_query_text(text)
    return any(token in normalized for token in ("别多嘴", "闭嘴", "别说话", "别回", "不要回", "少说", "安静", "别插嘴"))


# _looks_like_forwarded_chat_record：聊天处理
def _looks_like_forwarded_chat_record(text: str) -> bool:
    normalized = normalize_query_text(text)
    return "[聊天记录]" in normalized or "聊天记录" in normalized or "合并转发" in normalized


# _local_global_reaction_reason：本地reaction原因处理
def _local_global_reaction_reason(text: str, *, mentions_bot: bool) -> str:
    normalized = normalize_query_text(text)
    if not normalized or mentions_bot:
        return ""
    if any(token in normalized for token in ("想摸", "想舔", "想冲", "冲了", "擦边", "涩", "色", "骚", "烧", "老婆睡", "大果睡")):
        return "sexual_reaction_hint"
    if any(token in normalized for token in ("睡觉了", "晚安", "睡了", "困了", "先睡")):
        return "goodnight_reaction_hint"
    return ""


# _should_silence_trivial_global_message：消息处理
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


# _parse_group_response_mode：解析群聊模式JSON
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


# _extract_emoji_tag：提取表情
def _extract_emoji_tag(reply: str) -> str | None:
    normalized = normalize_query_text(reply)
    if not normalized:
        return None
    m = re.fullmatch(r"\[emoji:([a-zA-Z0-9_/\u4e00-\u9fa5]+)\]", normalized.strip())
    if not m:
        return None
    return str(m.group(1)).strip().lower()


# _should_use_reaction_instead：reaction处理
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
