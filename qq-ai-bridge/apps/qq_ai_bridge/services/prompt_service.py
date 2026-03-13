"""Prompt-building helpers for bridge tasks."""

import os
import re
from pathlib import Path
from typing import Any

from apps.qq_ai_bridge.config.settings import (
    GROUP_UPLOAD_DIR,
    MAX_FILE_CONTENT_LEN,
    OWNER_NAME,
    BASE_DATA_DIR,
)
from storage_utils import get_group_workspace, load_json_file, load_private_context, sample_style_lines
from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text
from apps.qq_ai_bridge.services.style_service import load_group_style_summary

SHORT_QUERY_LEN = 8
SHORT_QUERY_HISTORY_LIMIT = 2
NORMAL_QUERY_HISTORY_LIMIT = 6
SHORT_QUERY_HISTORY_CHAR_BUDGET = 220
NORMAL_QUERY_HISTORY_CHAR_BUDGET = 800
GROUP_COMPACT_QUERY_LEN = 8
GROUP_COMPACT_HISTORY_LIMIT = 2
GROUP_FULL_HISTORY_LIMIT = 4
GROUP_COMPACT_HISTORY_CHAR_BUDGET = 80
GROUP_FULL_HISTORY_CHAR_BUDGET = 220
GROUP_PERSONA_FULL_CHAR_BUDGET = 220
GROUP_PERSONA_COMPACT_CHAR_BUDGET = 72
GROUP_MARKDOWN_CHAR_BUDGET = 240
GROUP_BATCH_CHAR_BUDGET = 260

_GROUP_SOUL_CACHE = {
    "path": "",
    "mtime": None,
    "raw": "",
    "compact": "",
    "full": "",
}
_GROUP_MARKDOWN_CACHE: dict[str, dict[str, Any]] = {}


def prepare_private_ai_prompt(user_id, user_text: str) -> dict[str, Any]:
    """Build the private-chat LLM prompt and return prompt statistics."""
    context = load_private_context(BASE_DATA_DIR, user_id)
    query_len = len(user_text)
    is_short_query = query_len <= SHORT_QUERY_LEN
    history_limit = SHORT_QUERY_HISTORY_LIMIT if is_short_query else NORMAL_QUERY_HISTORY_LIMIT
    history = context["history"][-history_limit:]
    memory = context["memory"]
    history_turn_limit = 1 if query_len <= 4 else 2 if is_short_query else 5
    history_char_budget = SHORT_QUERY_HISTORY_CHAR_BUDGET if is_short_query else NORMAL_QUERY_HISTORY_CHAR_BUDGET
    style_sample_size = 0 if is_short_query else 6
    style_lines = sample_style_lines(context["style_samples_path"], sample_size=style_sample_size)

    history_lines = []
    history_chars = 0
    for item in reversed(history):
        user_part = str(item.get("user", "")).strip()
        bot_part = str(item.get("assistant", "")).strip()
        if user_part:
            line = f"User: {user_part}"
            line_len = len(line)
            if history_lines and (len(history_lines) >= history_turn_limit * 2 or history_chars + line_len > history_char_budget):
                break
            history_lines.insert(0, line)
            history_chars += line_len
        if bot_part:
            line = f"Assistant: {bot_part}"
            line_len = len(line)
            if history_lines and (len(history_lines) >= history_turn_limit * 2 or history_chars + line_len > history_char_budget):
                break
            history_lines.insert(0, line)
            history_chars += line_len

    if is_short_query:
        prompt_mode = "compact"
        prompt_parts = [
            "Reply naturally in this private QQ chat.",
            "Be brief, direct, and conversational.",
            f"User message: {user_text}",
        ]
        if history_lines:
            prompt_parts.insert(2, "Recent context:\n" + "\n".join(history_lines))
        if memory:
            prompt_parts.insert(2, "Memory:\n" + memory[:200])
    else:
        prompt_mode = "full"
        prompt_parts = [
            "You are replying in a private QQ chat.",
            "Respond naturally in Chinese unless the user clearly requests another language.",
            "Keep the answer useful and direct.",
        ]

        if memory:
            prompt_parts.append("Persistent memory:")
            prompt_parts.append(memory[:MAX_FILE_CONTENT_LEN])

        if history_lines:
            prompt_parts.append("Recent conversation history:")
            prompt_parts.append("\n".join(history_lines))

        if style_lines:
            prompt_parts.append("Here are examples of how this user speaks:")
            prompt_parts.append("\n".join(style_lines))

        prompt_parts.append(f"Current user message:\n{user_text}")

    prompt = "\n\n".join(prompt_parts)
    instruction_chars = sum(len(part) for part in prompt_parts[:-1]) if len(prompt_parts) > 1 else len(prompt)
    return {
        "prompt": prompt,
        "prompt_mode": prompt_mode,
        "query_len": query_len,
        "history_chars": history_chars,
        "history_items": len(history_lines),
        "history_turn_limit": history_turn_limit,
        "style_chars": sum(len(line) for line in style_lines),
        "instruction_chars": instruction_chars,
        "prompt_chars": len(prompt),
    }


def build_private_ai_prompt(user_id, user_text: str) -> str:
    """Build the private-chat LLM prompt with memory/history/style context."""
    return prepare_private_ai_prompt(user_id, user_text)["prompt"]


def build_vision_user_text(text: str) -> str:
    """Normalize optional user text that accompanies an image request."""
    text = normalize_query_text(text)
    text = re.sub(r"@\S+", " ", text)
    text = normalize_query_text(text)
    if text.startswith("ai "):
        text = normalize_query_text(text[3:])
    return text


def load_group_soul() -> str:
    """Load the current group persona file if present."""
    soul_info = _load_group_soul_cache()
    return soul_info["raw"]


def prepare_group_ai_prompt(group_id, user_text: str, user_id=None, log=None, batch_context: dict | None = None) -> dict[str, Any]:
    """Build a compact or full prompt for group chat and return prompt statistics."""
    normalized_text = normalize_query_text(user_text)
    query_len = len(normalized_text)
    prompt_mode = "compact" if query_len <= GROUP_COMPACT_QUERY_LEN else "full"
    soul_info = _load_group_soul_cache()
    persona = soul_info["compact"] if prompt_mode == "compact" else soul_info["full"]
    workspace = get_group_workspace(BASE_DATA_DIR, group_id)

    history_limit = GROUP_COMPACT_HISTORY_LIMIT if prompt_mode == "compact" else GROUP_FULL_HISTORY_LIMIT
    history_budget = GROUP_COMPACT_HISTORY_CHAR_BUDGET if prompt_mode == "compact" else GROUP_FULL_HISTORY_CHAR_BUDGET
    history_lines = _build_group_history_lines(workspace["chat_log_path"], history_limit, history_budget)
    history_text = "\n".join(history_lines)
    history_chars = len(history_text)

    style_section = load_group_style_summary(BASE_DATA_DIR, group_id, user_id=user_id, log=log)
    markdown_section = _load_group_markdown_context(group_id, log=log)
    batch_section = _build_group_batch_section(batch_context)

    privacy_rules = (
        "别泄露群友隐私，别提私聊内容、私有文件、真实身份信息。"
        f"你和{OWNER_NAME}很熟，但别硬提。"
    )

    if prompt_mode == "compact":
        prompt_parts = [
            "你在QQ群里接话。",
            persona,
            "自然点，别卖萌过头，别为了搞怪乱编。",
            privacy_rules,
        ]
        if history_text:
            prompt_parts.append("刚刚群里：" + history_text.replace("\n", " | "))
        if batch_section:
            prompt_parts.append(batch_section.replace("\n", " | "))
        if style_section:
            prompt_parts.append(style_section)
        if markdown_section:
            prompt_parts.append(markdown_section)
        prompt_parts.append("当前消息：" + normalized_text)
    else:
        prompt_parts = [
            "你正在QQ群聊里回复消息。",
            persona,
            "保持像群友，但别过度抽象、别突然喵化、别无意义胡闹。",
            privacy_rules,
            "默认是在参与气氛，不是认真客服式答题；除非对方明显在认真求助。",
        ]
        if history_text:
            prompt_parts.append("最近群聊上下文：\n" + history_text)
        if batch_section:
            prompt_parts.append(batch_section)
        if style_section:
            prompt_parts.append(style_section)
        if markdown_section:
            prompt_parts.append(markdown_section)
        prompt_parts.append("当前群聊消息：\n" + normalized_text)

    prompt = "\n\n".join(part for part in prompt_parts if part)
    instruction_parts = prompt_parts[:-1] if len(prompt_parts) > 1 else prompt_parts
    instruction_chars = sum(len(part) for part in instruction_parts)
    return {
        "prompt": prompt,
        "prompt_mode": prompt_mode,
        "query_len": query_len,
        "persona_chars": len(persona),
        "history_chars": history_chars,
        "history_items": len(history_lines),
        "style_chars": len(style_section),
        "markdown_chars": len(markdown_section),
        "batch_chars": len(batch_section),
        "current_message_chars": len(normalized_text),
        "instruction_chars": instruction_chars,
        "prompt_chars": len(prompt),
    }


def build_group_safe_prompt(group_id, user_text: str) -> str:
    """Build the group-chat prompt with cached persona and lightweight context."""
    return prepare_group_ai_prompt(group_id, user_text)["prompt"]


def _load_group_soul_cache() -> dict[str, str]:
    """Read SOUL.md once and refresh cached summaries only when the file changes."""
    soul_path = Path(GROUP_UPLOAD_DIR) / "SOUL.md"
    cache_path = str(soul_path)
    try:
        mtime = soul_path.stat().st_mtime
    except OSError as e:
        if _GROUP_SOUL_CACHE["path"] != cache_path or _GROUP_SOUL_CACHE["raw"]:
            print(f"[WARN] 无法读取群聊人格文件 {soul_path}: {e}")
        _GROUP_SOUL_CACHE.update({"path": cache_path, "mtime": None, "raw": "", "compact": _default_group_persona("compact"), "full": _default_group_persona("full")})
        return _GROUP_SOUL_CACHE

    try:
        if _GROUP_SOUL_CACHE["path"] == cache_path and _GROUP_SOUL_CACHE["mtime"] == mtime:
            return _GROUP_SOUL_CACHE

        raw = soul_path.read_text(encoding="utf-8")
    except Exception as e:
        print(f"[WARN] 无法读取群聊人格文件 {soul_path}: {e}")
        _GROUP_SOUL_CACHE.update({"path": cache_path, "mtime": None, "raw": "", "compact": _default_group_persona("compact"), "full": _default_group_persona("full")})
        return _GROUP_SOUL_CACHE

    compact = _summarize_group_persona(raw, mode="compact")
    full = _summarize_group_persona(raw, mode="full")
    _GROUP_SOUL_CACHE.update({"path": cache_path, "mtime": mtime, "raw": raw, "compact": compact, "full": full})
    print(
        "[GROUP_PROMPT] soul loaded"
        f" path={soul_path}"
        f" raw_chars={len(raw)}"
        f" compact_chars={len(compact)}"
        f" full_chars={len(full)}"
    )
    return _GROUP_SOUL_CACHE


def _default_group_persona(mode: str) -> str:
    if mode == "compact":
        return "单行短句，像群友接话。自然点，别像AI，不过火。"
    return (
        "单行、短句、口语化，像熟人群聊。别像AI或客服。"
        "优先接梗、附和、轻吐槽，保留一点抽象感，但别演过头。"
    )


def _summarize_group_persona(raw_text: str, mode: str) -> str:
    base = _default_group_persona(mode)
    if not raw_text.strip():
        return base

    hints = _extract_persona_hints(raw_text)
    budget = GROUP_PERSONA_COMPACT_CHAR_BUDGET if mode == "compact" else GROUP_PERSONA_FULL_CHAR_BUDGET
    summary = base
    for hint in hints:
        candidate = f"{summary} {hint}".strip()
        if len(candidate) > budget:
            break
        summary = candidate
    return summary


def _extract_persona_hints(raw_text: str) -> list[str]:
    keywords = (
        "单行", "短句", "自然", "别像AI", "不像AI", "像群友", "轻微抽象", "抽象", "接梗", "附和",
        "吐槽", "口语", "复读", "别说教", "别端着", "别写长文", "别换行",
    )
    hints = []
    seen = set()
    lines = [line.strip(" -*#\t") for line in raw_text.splitlines()]
    for line in lines:
        clean = re.sub(r"\*\*(.*?)\*\*", r"\1", line)
        clean = re.sub(r"^\d+\.\s*", "", clean)
        clean = " ".join(clean.split()).strip(" -*#\t")
        if not clean:
            continue
        if len(clean) > 36:
            clean = clean[:36].rstrip("，。；,.; ")
        if not any(keyword in line for keyword in keywords):
            continue
        if clean in seen:
            continue
        seen.add(clean)
        hints.append(clean)
    return hints[:8]


def _build_group_history_lines(chat_log_path: str, history_limit: int, history_char_budget: int) -> list[str]:
    chat_log = load_json_file(chat_log_path, [])
    lines: list[str] = []
    total_chars = 0
    for item in reversed(chat_log[-history_limit:]):
        user_id = item.get("sender_name") or item.get("user_id", "?")
        message = normalize_query_text(str(item.get("message", "")).strip())
        if not message:
            continue
        line = f"{user_id}: {message}"
        line_len = len(line)
        if lines and total_chars + line_len > history_char_budget:
            break
        lines.insert(0, line)
        total_chars += line_len
    return lines


def _build_group_batch_section(batch_context: dict | None) -> str:
    if not batch_context:
        return ""
    merged_blocks = batch_context.get("merged_blocks", [])
    if not isinstance(merged_blocks, list) or len(merged_blocks) <= 1:
        return ""

    lines = []
    total_chars = 0
    for block in merged_blocks:
        sender_name = normalize_query_text(str(block.get("sender_name", "")).strip()) or "群友"
        texts = [normalize_query_text(str(text).strip()) for text in block.get("texts", [])]
        merged_line = " | ".join(text for text in texts if text)
        if not merged_line:
            continue
        line = f"{sender_name}：{merged_line}"
        if lines and total_chars + len(line) > GROUP_BATCH_CHAR_BUDGET:
            break
        lines.append(line)
        total_chars += len(line)
    if not lines:
        return ""
    return "本轮合并消息：\n" + "\n".join(lines)


def _load_group_markdown_context(group_id, log=None) -> str:
    workspace = get_group_workspace(BASE_DATA_DIR, group_id)
    candidate_dirs = [
        Path(workspace["dir"]),
        Path(GROUP_UPLOAD_DIR) / str(group_id),
    ]

    files: list[Path] = []
    for directory in candidate_dirs:
        if not directory.exists() or not directory.is_dir():
            continue
        files.extend(sorted(directory.glob("*.md")))

    unique_files: list[Path] = []
    seen = set()
    for path in files:
        resolved = str(path.resolve())
        if resolved in seen:
            continue
        seen.add(resolved)
        unique_files.append(path)

    signatures = []
    for path in unique_files:
        try:
            stat = path.stat()
        except OSError:
            continue
        signatures.append((str(path), stat.st_mtime, stat.st_size))

    cache_key = str(group_id)
    cached = _GROUP_MARKDOWN_CACHE.get(cache_key)
    if cached and cached.get("signatures") == signatures:
        return cached.get("summary", "")

    summary = _summarize_group_markdown_files(unique_files)
    _GROUP_MARKDOWN_CACHE[cache_key] = {"signatures": signatures, "summary": summary}
    if summary and log:
        log(
            "[GROUP_PROMPT] markdown loaded"
            f" group_id={group_id}"
            f" file_count={len(unique_files)}"
            f" summary_chars={len(summary)}"
        )
    return summary


def _summarize_group_markdown_files(paths: list[Path]) -> str:
    if not paths:
        return ""

    snippets = []
    total_chars = 0
    sorted_paths = sorted(paths, key=lambda path: path.stat().st_mtime if path.exists() else 0, reverse=True)
    for path in sorted_paths[:3]:
        try:
            raw = path.read_text(encoding="utf-8")
        except Exception:
            continue
        cleaned_lines = []
        for line in raw.splitlines():
            clean = re.sub(r"\s+", " ", line.strip(" -*#\t"))
            if not clean:
                continue
            if len(clean) > 36:
                clean = clean[:36].rstrip("，。；,.; ")
            cleaned_lines.append(clean)
            if len(cleaned_lines) >= 4:
                break
        if not cleaned_lines:
            continue
        snippet = f"{path.stem}：" + " / ".join(cleaned_lines)
        if snippets and total_chars + len(snippet) > GROUP_MARKDOWN_CHAR_BUDGET:
            break
        snippets.append(snippet)
        total_chars += len(snippet)

    if not snippets:
        return ""
    return "群文件补充话术： " + "；".join(snippets)
