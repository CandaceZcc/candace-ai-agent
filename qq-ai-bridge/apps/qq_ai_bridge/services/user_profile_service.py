"""Lightweight structured user profile extraction for private chat."""

from __future__ import annotations

import re

from storage_utils import get_user_workspace, load_json_file, save_json_file

from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text

_MAX_ITEMS = 8
_MAX_RECENT_TOPICS = 5
_TOPIC_STOPWORDS = {
    "今天", "现在", "最近", "这个", "那个", "一下", "有点", "真的", "感觉", "就是", "然后",
    "一个", "你说", "我们", "他们", "自己", "可以", "还是", "因为", "所以", "什么", "怎么",
}


# update_private_user_profile：更新私聊用户画像
def update_private_user_profile(base_dir: str, user_id, message: str, log=None) -> dict:
    text = str(message or "").strip()
    normalized = normalize_query_text(text)
    if not normalized:
        return {}

    workspace = get_user_workspace(base_dir, user_id)
    path = workspace["profile_path"]
    profile = _normalize_profile(load_json_file(path, {}))

    for value in _extract_preferences(text, normalized, positive=True):
        _push_unique(profile["likes"], value)
    for value in _extract_preferences(text, normalized, positive=False):
        _push_unique(profile["dislikes"], value)
    for value in _extract_identity_tags(text):
        _push_unique(profile["identity_tags"], value)
    for value in _extract_recent_topics(text):
        _push_unique(profile["recent_topics"], value, limit=_MAX_RECENT_TOPICS)

    profile["last_message"] = text[:160]
    save_json_file(path, profile)
    if log:
        log(
            f"[PROFILE] updated user_id={user_id}"
            f" likes={len(profile['likes'])}"
            f" dislikes={len(profile['dislikes'])}"
            f" identity={len(profile['identity_tags'])}"
            f" topics={len(profile['recent_topics'])}"
        )
    return profile


# load_private_user_profile_summary：加载用户画像摘要
def load_private_user_profile_summary(base_dir: str, user_id) -> str:
    workspace = get_user_workspace(base_dir, user_id)
    profile = _normalize_profile(load_json_file(workspace["profile_path"], {}))
    parts: list[str] = []
    if profile["identity_tags"]:
        parts.append("身份：" + "/".join(profile["identity_tags"][:3]))
    if profile["likes"]:
        parts.append("偏好：" + "/".join(profile["likes"][:4]))
    if profile["dislikes"]:
        parts.append("不喜欢：" + "/".join(profile["dislikes"][:3]))
    if profile["recent_topics"]:
        parts.append("最近在聊：" + "/".join(profile["recent_topics"][:3]))
    summary = "；".join(parts)
    return summary[:180].rstrip("，。；,.; ")


# _normalize_profile：规范化画像
def _normalize_profile(raw: dict) -> dict:
    if not isinstance(raw, dict):
        raw = {}
    return {
        "likes": _normalize_str_list(raw.get("likes", [])),
        "dislikes": _normalize_str_list(raw.get("dislikes", [])),
        "identity_tags": _normalize_str_list(raw.get("identity_tags", [])),
        "recent_topics": _normalize_str_list(raw.get("recent_topics", []), limit=_MAX_RECENT_TOPICS),
        "last_message": str(raw.get("last_message", "") or "").strip(),
    }


# _normalize_str_list：规范化相关逻辑
def _normalize_str_list(values, limit: int = _MAX_ITEMS) -> list[str]:
    if not isinstance(values, list):
        return []
    normalized: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in normalized:
            continue
        normalized.append(text)
        if len(normalized) >= limit:
            break
    return normalized


# _extract_preferences：提取偏好
def _extract_preferences(text: str, normalized: str, positive: bool) -> list[str]:
    seeds = []
    verbs = ("喜欢", "爱", "想看", "想买", "常听", "常玩") if positive else ("讨厌", "不喜欢", "受不了", "烦", "不想要")
    for verb in verbs:
        idx = normalized.find(verb)
        if idx < 0:
            continue
        tail = text[idx + len(verb):]
        seeds.extend(_split_preference_tail(tail))
    return seeds[:4]


# _split_preference_tail：拆分偏好
def _split_preference_tail(tail: str) -> list[str]:
    tail = re.split(r"[。！？!?\n]", str(tail or ""), maxsplit=1)[0]
    tail = re.sub(r"^(的|那种|这种)+", "", tail).strip(" ，,、/")
    if not tail:
        return []
    chunks = re.split(r"[，,、]|也喜欢|和|以及|还有|但是|不过", tail)
    results = []
    for chunk in chunks:
        clean = re.sub(r"^(特别|很|比较|有点)", "", chunk).strip(" ，,、/")
        clean = re.sub(r"(的人|这件事|这种东西)$", "", clean).strip(" ，,、/")
        if 1 <= len(clean) <= 18:
            results.append(clean)
    return results[:4]


# _extract_identity_tags：提取身份标签
def _extract_identity_tags(text: str) -> list[str]:
    tags = []
    patterns = (
        r"我是([^\s，。！？,!?]{1,16})",
        r"我在([^，。！？,!?]{1,16})上学",
        r"我做([^，。！？,!?]{1,16})",
    )
    for pattern in patterns:
        for match in re.findall(pattern, text):
            clean = str(match).strip(" ，,。！？!?")
            if clean:
                tags.append(clean)
    return tags[:3]


# _extract_recent_topics：提取近期话题
def _extract_recent_topics(text: str) -> list[str]:
    candidates = re.findall(r"[A-Za-z][A-Za-z0-9.+_-]{2,}|[\u4e00-\u9fff]{2,8}", text)
    topics = []
    for item in candidates:
        if item in _TOPIC_STOPWORDS:
            continue
        if item.startswith("我") and len(item) <= 3:
            continue
        topics.append(item)
    deduped: list[str] = []
    for topic in topics:
        if topic not in deduped:
            deduped.append(topic)
        if len(deduped) >= _MAX_RECENT_TOPICS:
            break
    return deduped


# _push_unique：加入唯一
def _push_unique(items: list[str], value: str, limit: int = _MAX_ITEMS) -> None:
    clean = str(value or "").strip()
    if not clean:
        return
    if clean in items:
        items.remove(clean)
    items.insert(0, clean)
    del items[limit:]
