import base64
import mimetypes
import os

import requests


def build_vision_prompt(user_text: str) -> str:
    text = str(user_text or "").strip()
    if not text:
        return "请简洁描述图片里有什么，语气自然，像聊天回复。"
    return (
        "请结合图片回答用户问题，回复简洁自然。"
        "如果用户是在问图片内容，就直接回答。"
        "如果用户要提取图中文字，就优先提取文字。"
        f"\n用户补充：{text}"
    )


def analyze_image(image_path: str, user_text: str = "") -> str:
    api_url = os.environ.get("VISION_API_URL", "").strip()
    api_key = os.environ.get("VISION_API_KEY", "").strip()
    model = os.environ.get("VISION_MODEL", "").strip()

    if not api_url or not api_key or not model:
        return "识图功能还没配置好"

    try:
        payload = _build_request_payload(image_path, user_text=user_text, model=model)
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        resp = requests.post(api_url, json=payload, headers=headers, timeout=60)
        resp.raise_for_status()
        data = resp.json()
        content = _extract_response_text(data)
        return content or "我看了图，但暂时没整理出结果"
    except Exception:
        return "看图的时候出了点问题"


def _build_request_payload(image_path: str, user_text: str, model: str) -> dict:
    mime_type = mimetypes.guess_type(image_path)[0] or "image/jpeg"
    with open(image_path, "rb") as f:
        encoded = base64.b64encode(f.read()).decode("utf-8")
    image_url = f"data:{mime_type};base64,{encoded}"

    return {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "你是一个看图助手，回答要简短、自然、像聊天。"
            },
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": build_vision_prompt(user_text)},
                    {"type": "image_url", "image_url": {"url": image_url}}
                ]
            }
        ]
    }


def _extract_response_text(data) -> str:
    if not isinstance(data, dict):
        return ""

    if isinstance(data.get("reply"), str):
        return data.get("reply", "").strip()
    if isinstance(data.get("text"), str):
        return data.get("text", "").strip()

    choices = data.get("choices")
    if isinstance(choices, list) and choices:
        message = choices[0].get("message", {})
        content = message.get("content")
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict) and item.get("type") == "text":
                    text = str(item.get("text", "")).strip()
                    if text:
                        parts.append(text)
            return " ".join(parts).strip()

    return ""
