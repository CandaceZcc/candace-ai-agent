"""QQ emoji helpers.

Reference:
- Moonlark uses a QQ emoji id-name mapping in `qq_emoji.json`.
"""

from __future__ import annotations

import random
import re

# Keep this compact and focused on commonly used reactions.
QQ_EMOJI_NAME_TO_ID: dict[str, int] = {
    "笑哭": 182,
    "捂脸": 264,
    "棒棒糖": 147,
    "爱心": 66,
    "点赞": 201,
    "问号": 268,
}

DEFAULT_EMOJI_SEQUENCE: tuple[str, ...] = ("笑哭", "捂脸", "棒棒糖", "爱心")
_EMOJI_REQUEST_PATTERN = re.compile(r"(贴|发|来个|给我).{0,4}(表情|emoji|face)")


def is_emoji_request(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    if "贴表情" in normalized or "给我贴个表情" in normalized:
        return True
    return bool(_EMOJI_REQUEST_PATTERN.search(normalized))


def extract_emoji_name(text: str) -> str | None:
    normalized = str(text or "")
    for name in QQ_EMOJI_NAME_TO_ID:
        if name in normalized:
            return name
    return None


def build_face_cq(emoji_name: str) -> str | None:
    face_id = QQ_EMOJI_NAME_TO_ID.get(emoji_name)
    if face_id is None:
        return None
    return f"[CQ:face,id={face_id}]"


def pick_face_cq(seed: str = "", preferred: tuple[str, ...] = DEFAULT_EMOJI_SEQUENCE) -> tuple[str, str]:
    names = [name for name in preferred if name in QQ_EMOJI_NAME_TO_ID]
    if not names:
        names = list(QQ_EMOJI_NAME_TO_ID.keys())
    if not names:
        return ("笑哭", "[CQ:face,id=182]")
    idx = abs(hash(seed or "default")) % len(names)
    name = names[idx]
    return name, build_face_cq(name) or "[CQ:face,id=182]"


__all__ = [
    "QQ_EMOJI_NAME_TO_ID",
    "build_face_cq",
    "extract_emoji_name",
    "is_emoji_request",
    "pick_face_cq",
]
