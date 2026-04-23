"""Lightweight meme / sticker matcher skeleton."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from PIL import Image

from apps.qq_ai_bridge.config.settings import BASE_DATA_DIR

MEME_LIBRARY_DIR = Path(BASE_DATA_DIR) / "memes"


@dataclass
class MemeMatchResult:
    """Matched meme template metadata."""

    matched: bool
    tag: str = ""
    confidence: float = 0.0
    suggested_action: str = "no_reply"
    short_text: str | None = None
    emoji_name: str | None = None


def match_meme(image_path: str, ocr_keywords: Iterable[str] | None = None) -> MemeMatchResult:
    """Try a lightweight local meme match with future-proof extension points."""
    path = Path(image_path)
    if not path.exists():
        return MemeMatchResult(matched=False)

    tags = set(str(item).strip().lower() for item in (ocr_keywords or []) if str(item).strip())
    if {"无语", "绷不住", "笑死"} & tags:
        return MemeMatchResult(matched=True, tag="laugh", confidence=0.74, suggested_action="reaction", emoji_name="laugh_cry")

    try:
        image_hash = _compute_dhash(path)
    except Exception:
        return MemeMatchResult(matched=False)

    for template_path in MEME_LIBRARY_DIR.glob("**/*"):
        if not template_path.is_file():
            continue
        try:
            template_hash = _compute_dhash(template_path)
        except Exception:
            continue
        distance = _hamming_distance(image_hash, template_hash)
        if distance <= 6:
            tag = template_path.parent.name or "unknown"
            return MemeMatchResult(
                matched=True,
                tag=tag,
                confidence=max(0.4, 1 - distance / 16),
                suggested_action="reaction",
                emoji_name="laugh_cry" if tag in {"无语", "绷不住", "哭笑"} else "red_button",
            )
    return MemeMatchResult(matched=False)


def _compute_dhash(path: Path, size: int = 8) -> int:
    with Image.open(path) as image:
        grayscale = image.convert("L").resize((size + 1, size))
        pixels = list(grayscale.getdata())
    value = 0
    for row in range(size):
        for col in range(size):
            left = pixels[row * (size + 1) + col]
            right = pixels[row * (size + 1) + col + 1]
            value = (value << 1) | int(left > right)
    return value


def _hamming_distance(left: int, right: int) -> int:
    return (left ^ right).bit_count()

