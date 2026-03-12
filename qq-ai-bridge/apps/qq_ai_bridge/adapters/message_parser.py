"""Message parsing helpers for QQ payloads."""

import re


def normalize_query_text(text: str) -> str:
    if text is None:
        return ""
    normalized = re.sub(r"\s+", " ", str(text).strip())
    return normalized if normalized.strip() else ""


def extract_text_and_mention(event_data, self_id):
    """Parse text and @-mention state from OneBot/NapCat payloads."""
    text_parts = []
    mentioned_self = False

    raw_message = event_data.get("message")
    if isinstance(raw_message, str):
        return normalize_query_text(raw_message), False

    if isinstance(raw_message, list):
        for seg in raw_message:
            if not isinstance(seg, dict):
                continue

            seg_type = seg.get("type")
            data = seg.get("data", {})

            if seg_type == "text":
                text = normalize_query_text(data.get("text", ""))
                if text:
                    text_parts.append(text)
            elif seg_type == "at":
                qq = str(data.get("qq", ""))
                if qq == str(self_id):
                    mentioned_self = True

        return "".join(text_parts).strip(), mentioned_self

    elements = event_data.get("elements", [])
    if isinstance(elements, list):
        for elem in elements:
            if not isinstance(elem, dict):
                continue

            text_elem = elem.get("textElement")
            if isinstance(text_elem, dict):
                for key in ("content", "text", "atText"):
                    content = normalize_query_text(text_elem.get(key, ""))
                    if content:
                        text_parts.append(content)
                        break

            if str(elem.get("atType")) == "1":
                mentioned_self = True

        return "".join(text_parts).strip(), mentioned_self

    return "", False


def has_meaningful_text(event_data, self_id) -> bool:
    text, _ = extract_text_and_mention(event_data, self_id)
    return normalize_query_text(text) != ""
