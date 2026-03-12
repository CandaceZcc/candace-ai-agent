"""Lightweight style learning for group chat."""

from __future__ import annotations

import math
import time

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text
from storage_utils import get_group_workspace, load_json_file, save_json_file

SUMMARY_VERSION = 1
MAX_TOKEN_COUNTS = 16
MAX_ENDING_COUNTS = 12
COMMON_TONE_WORDS = ("啊", "呀", "呢", "吧", "哈", "草", "笑死", "确实", "典", "离谱", "牛逼", "吗", "喵")
ABSTRACT_HINTS = ("抽象", "典", "绷", "草", "笑死", "逆天", "离谱")
CUTE_HINTS = ("喵", "捏", "呀", "哇", "欸")
COLD_HINTS = ("哦", "行", "随便", "还行", "一般", "无所谓")


def capture_group_style(base_dir: str, group_id, user_id, message: str, log=print) -> None:
    """Update per-group and per-user style profiles for group messages."""
    text = normalize_query_text(message)
    if not text:
        return

    workspace = get_group_workspace(base_dir, group_id)
    user_profile_path = workspace["style_user_profile_path"](user_id)
    group_profile_path = workspace["style_group_profile_path"]

    log(f"[STYLE] captured group_id={group_id} user_id={user_id} chars={len(text)}")
    _update_style_profile(user_profile_path, text, scope=f"group:{group_id}:user:{user_id}", log=log)
    _update_style_profile(group_profile_path, text, scope=f"group:{group_id}:all", log=log)


def load_group_style_summary(base_dir: str, group_id, user_id=None, log=None) -> str:
    """Return a short style summary for the group and optionally the sender."""
    workspace = get_group_workspace(base_dir, group_id)
    summaries: list[str] = []

    group_profile = load_json_file(workspace["style_group_profile_path"], _default_style_profile())
    group_summary = str(group_profile.get("summary", "")).strip()
    if group_summary:
        summaries.append(f"群整体语气：{group_summary}")

    if user_id is not None:
        user_profile = load_json_file(workspace["style_user_profile_path"](user_id), _default_style_profile())
        user_summary = str(user_profile.get("summary", "")).strip()
        if user_summary:
            summaries.append(f"这个人常见说法：{user_summary}")

    summary = "；".join(summaries[:2])
    if summary and log:
        log(
            "[STYLE] applied"
            f" group_id={group_id}"
            f" user_id={user_id}"
            f" summary_chars={len(summary)}"
        )
    return summary


def _update_style_profile(path: str, text: str, scope: str, log=print) -> None:
    profile = load_json_file(path, _default_style_profile())
    profile = _merge_style_features(profile, text)
    profile["summary"] = _build_style_summary(profile)
    save_json_file(path, profile)
    log(
        "[STYLE] updated"
        f" scope={scope}"
        f" samples={profile['message_count']}"
        f" avg_len={profile['avg_length']}"
        f" traits={','.join(profile['trait_tags']) or 'none'}"
    )


def _default_style_profile() -> dict:
    return {
        "version": SUMMARY_VERSION,
        "message_count": 0,
        "avg_length": 0,
        "rhetorical_ratio": 0.0,
        "tone_words": {},
        "ending_habits": {},
        "trait_scores": {"abstract": 0, "cold": 0, "cute": 0},
        "trait_tags": [],
        "summary": "",
        "updated_at": 0,
    }


def _merge_style_features(profile: dict, text: str) -> dict:
    count = int(profile.get("message_count", 0)) + 1
    prev_avg = float(profile.get("avg_length", 0))
    length = len(text)
    avg_length = round(((prev_avg * (count - 1)) + length) / count, 1)

    rhetorical = 1.0 if ("?" in text or "？" in text or text.endswith("吗")) else 0.0
    prev_ratio = float(profile.get("rhetorical_ratio", 0.0))
    rhetorical_ratio = round(((prev_ratio * (count - 1)) + rhetorical) / count, 3)

    tone_words = dict(profile.get("tone_words", {}))
    for word in COMMON_TONE_WORDS:
        if word in text:
            tone_words[word] = int(tone_words.get(word, 0)) + text.count(word)
    tone_words = _trim_top_counts(tone_words, MAX_TOKEN_COUNTS)

    ending_habits = dict(profile.get("ending_habits", {}))
    ending = _detect_ending(text)
    if ending:
        ending_habits[ending] = int(ending_habits.get(ending, 0)) + 1
    ending_habits = _trim_top_counts(ending_habits, MAX_ENDING_COUNTS)

    trait_scores = dict(profile.get("trait_scores", {}))
    trait_scores["abstract"] = int(trait_scores.get("abstract", 0)) + _count_matches(text, ABSTRACT_HINTS)
    trait_scores["cold"] = int(trait_scores.get("cold", 0)) + _count_matches(text, COLD_HINTS)
    trait_scores["cute"] = int(trait_scores.get("cute", 0)) + _count_matches(text, CUTE_HINTS)

    return {
        "version": SUMMARY_VERSION,
        "message_count": count,
        "avg_length": avg_length,
        "rhetorical_ratio": rhetorical_ratio,
        "tone_words": tone_words,
        "ending_habits": ending_habits,
        "trait_scores": trait_scores,
        "trait_tags": _build_trait_tags(trait_scores, count),
        "summary": str(profile.get("summary", "")),
        "updated_at": int(time.time()),
    }


def _build_style_summary(profile: dict) -> str:
    parts: list[str] = []
    avg_length = float(profile.get("avg_length", 0))
    if avg_length <= 8:
        parts.append("句子偏短")
    elif avg_length >= 18:
        parts.append("句子偏长")
    else:
        parts.append("句长中等")

    rhetorical_ratio = float(profile.get("rhetorical_ratio", 0.0))
    if rhetorical_ratio >= 0.35:
        parts.append("偶尔爱反问")
    elif rhetorical_ratio <= 0.08:
        parts.append("很少反问")

    top_tones = [key for key, _ in _sorted_counts(profile.get("tone_words", {}))[:3]]
    if top_tones:
        parts.append("常用语气词：" + "/".join(top_tones))

    top_endings = [key for key, _ in _sorted_counts(profile.get("ending_habits", {}))[:2]]
    if top_endings:
        parts.append("常见收尾：" + "/".join(top_endings))

    tags = profile.get("trait_tags", [])
    if tags:
        parts.append("风格标签：" + "/".join(tags[:2]))

    summary = "，".join(parts).strip("，")
    if len(summary) > 120:
        summary = summary[:120].rstrip("，。；,.; ")
    return summary


def _build_trait_tags(scores: dict, message_count: int) -> list[str]:
    tags = []
    baseline = max(1, math.ceil(message_count / 8))
    if int(scores.get("abstract", 0)) >= baseline:
        tags.append("抽象")
    if int(scores.get("cold", 0)) >= baseline:
        tags.append("冷淡")
    if int(scores.get("cute", 0)) >= baseline:
        tags.append("轻可爱")
    return tags[:3]


def _detect_ending(text: str) -> str:
    stripped = text.strip()
    for size in (2, 1):
        if len(stripped) >= size:
            ending = stripped[-size:]
            if ending.strip():
                return ending
    return ""


def _trim_top_counts(data: dict[str, int], limit: int) -> dict[str, int]:
    return dict(_sorted_counts(data)[:limit])


def _sorted_counts(data: dict[str, int]) -> list[tuple[str, int]]:
    return sorted(data.items(), key=lambda item: (-int(item[1]), item[0]))


def _count_matches(text: str, patterns: tuple[str, ...]) -> int:
    return sum(text.count(pattern) for pattern in patterns)
