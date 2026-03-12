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


def extract_forward_id(event_data) -> str:
    """Try to find a merged-forward identifier in OneBot/NapCat payloads."""
    for seg in _iter_message_segments(event_data):
        seg_type = str(seg.get("type", "")).lower()
        data = seg.get("data", {}) if isinstance(seg.get("data"), dict) else {}
        if seg_type in {"forward", "node"}:
            for key in ("id", "res_id", "forward_id", "message_id"):
                value = data.get(key) or seg.get(key)
                if value:
                    return str(value)
    return ""


def format_forward_messages(payload) -> str:
    """Format merged-forward payload into readable plain text."""
    nodes = _extract_forward_nodes(payload)
    lines = []
    for node in nodes:
        name = _node_name(node)
        content = _node_content(node)
        if not content:
            continue
        lines.append(f"{name}：{content}")
    return "\n".join(lines).strip()


def _iter_message_segments(event_data):
    raw_message = event_data.get("message")
    if isinstance(raw_message, list):
        for seg in raw_message:
            if isinstance(seg, dict):
                yield seg
    elements = event_data.get("elements")
    if isinstance(elements, list):
        for elem in elements:
            if not isinstance(elem, dict):
                continue
            forward_element = elem.get("forwardElement")
            if isinstance(forward_element, dict):
                yield {"type": "forward", "data": forward_element}


def _extract_forward_nodes(payload) -> list[dict]:
    if not isinstance(payload, dict):
        return []
    candidates = []
    for key in ("data", "message", "messages", "content"):
        value = payload.get(key)
        if isinstance(value, list):
            candidates.extend(item for item in value if isinstance(item, dict))
        elif isinstance(value, dict):
            for nested_key in ("message", "messages", "content"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, list):
                    candidates.extend(item for item in nested_value if isinstance(item, dict))
    return candidates


def _node_name(node: dict) -> str:
    for key in ("name", "nickname", "sender", "user_name"):
        value = node.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, dict):
            for nested_key in ("nickname", "name", "card"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, str) and nested_value.strip():
                    return nested_value.strip()
    return "转发消息"


def _node_content(node: dict) -> str:
    for key in ("content", "message", "messages"):
        text = _content_to_text(node.get(key))
        if text:
            return text
    data = node.get("data")
    if isinstance(data, dict):
        for key in ("content", "message", "messages"):
            text = _content_to_text(data.get(key))
            if text:
                return text
    return ""


def _content_to_text(value) -> str:
    if isinstance(value, str):
        return _filter_forward_content(normalize_query_text(value))
    if isinstance(value, list):
        parts = []
        for item in value:
            if isinstance(item, str):
                text = _filter_forward_content(normalize_query_text(item))
                if text:
                    parts.append(text)
                continue
            if not isinstance(item, dict):
                continue
            seg_type = item.get("type")
            data = item.get("data", {}) if isinstance(item.get("data"), dict) else {}
            if seg_type == "text":
                text = _filter_forward_content(normalize_query_text(data.get("text", "")))
                if text:
                    parts.append(text)
            else:
                nested = _filter_forward_content(normalize_query_text(str(data.get("content", "") or data.get("text", ""))))
                if nested:
                    parts.append(nested)
        return " ".join(parts).strip()
    if isinstance(value, dict):
        for key in ("text", "content"):
            text = _filter_forward_content(normalize_query_text(value.get(key, "")))
            if text:
                return text
    return ""


def _filter_forward_content(text: str) -> str:
    blocked = {
        "请求超时",
        "ocai 处理超时",
        "completed",
        "processing",
        "done",
    }
    normalized = normalize_query_text(text)
    if not normalized:
        return ""
    lowered = normalized.lower()
    if lowered in blocked:
        return ""
    if any(token in lowered for token in ("请求超时", "ocai 处理超时")):
        return ""
    if lowered in {"completed", "processing", "done"}:
        return ""
    return normalized
