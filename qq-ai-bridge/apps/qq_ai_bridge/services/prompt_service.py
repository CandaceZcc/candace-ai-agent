"""Prompt-building helpers for bridge tasks."""

import os

from apps.qq_ai_bridge.config.settings import (
    GROUP_UPLOAD_DIR,
    MAX_FILE_CONTENT_LEN,
    OWNER_NAME,
    BASE_DATA_DIR,
)
from storage_utils import get_group_workspace, load_private_context, sample_style_lines
from apps.qq_ai_bridge.adapters.message_parser import normalize_query_text


def build_private_ai_prompt(user_id, user_text: str) -> str:
    """Build the private-chat LLM prompt with memory/history/style context."""
    context = load_private_context(BASE_DATA_DIR, user_id)
    history = context["history"][-20:]
    memory = context["memory"]
    style_lines = sample_style_lines(context["style_samples_path"], sample_size=10)

    history_lines = []
    for item in history:
        user_part = str(item.get("user", "")).strip()
        bot_part = str(item.get("assistant", "")).strip()
        if user_part:
            history_lines.append(f"User: {user_part}")
        if bot_part:
            history_lines.append(f"Assistant: {bot_part}")

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
        prompt_parts.append("\n".join(history_lines[-40:]))

    if style_lines:
        prompt_parts.append("Here are examples of how this user speaks:")
        prompt_parts.append("\n".join(style_lines))

    prompt_parts.append(f"Current user message:\n{user_text}")
    return "\n\n".join(prompt_parts)


def build_vision_user_text(text: str) -> str:
    """Normalize optional user text that accompanies an image request."""
    text = normalize_query_text(text)
    if text.startswith("ai "):
        text = normalize_query_text(text[3:])
    return text


def load_group_soul() -> str:
    """Load the current group persona file if present."""
    soul_path = os.path.join(GROUP_UPLOAD_DIR, "SOUL.md")
    try:
        with open(soul_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        print(f"[WARN] 无法读取群聊人格文件 {soul_path}: {e}")
        return ""


def build_group_safe_prompt(group_id, user_text: str) -> str:
    """Build the group-chat prompt with persona, privacy rules, and style samples."""
    group_soul = load_group_soul()
    workspace = get_group_workspace(BASE_DATA_DIR, group_id)
    style_lines = sample_style_lines(workspace["style_samples_path"], sample_size=10)
    style_section = ""
    if style_lines:
        style_section = (
            "\n# 群聊风格样本\n"
            "下面是这个群平时说话的一些样子，你可以轻微模仿语气，但不要照抄：\n"
            + "\n".join(style_lines)
        )

    return f"""你正在一个QQ群聊中回复消息。

# 你的群聊人格设定
{group_soul}

# 隐私保护规则（必须遵守）
1. 不要输出、猜测、总结或泄露任何用户的个人隐私信息。
2. 不要提及私聊中出现过的内容。
3. 不要提及私有文件、私有笔记、私有路径、私有身份信息。
4. 不要输出用户的QQ号、邮箱、学校、住址、账号、真实姓名、个人经历等敏感信息。
5. 如果问题涉及个人信息或私密内容，直接拒绝并简短说明无法在群聊中提供。
6. 你记得你的主人叫 {OWNER_NAME}，和你很熟；只有在非常自然的时候才顺手提一下，不要生硬自我介绍。
7. 在群聊里，默认不是认真回答问题，而是参与气氛。除非对方明显认真求助，否则优先接梗、附和、吐槽、复读关键词，而不是完整解答。
8. 回复尽量像群友，不像客服。允许半句、打断、口头禅式表达。
9. 不要换行，不要写成多段。
10. 优先短句、口语化。
{style_section}

当前群聊消息：
{user_text}"""
