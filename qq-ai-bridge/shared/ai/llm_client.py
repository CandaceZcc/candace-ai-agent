"""LLM client helpers."""

import subprocess

from apps.qq_ai_bridge.config.settings import AI_CMD


def call_ai(text: str) -> str:
    """Call the local LLM CLI and return text output."""
    print(f"[OCAI] 开始调用 ocai，参数前200字符: {text[:200]!r}")

    try:
        result = subprocess.check_output(
            [AI_CMD, text],
            stderr=subprocess.STDOUT,
            timeout=180,
        )
        output = result.decode("utf-8", errors="ignore").strip()

        if not output:
            output = "ocai 没有返回内容。"

        print(f"[OCAI] 调用成功，输出前300字符:\n{output[:300]}")
        return output
    except subprocess.CalledProcessError as e:
        output = e.output.decode("utf-8", errors="ignore")
        print(f"[OCAI] CalledProcessError:\n{output}")
        return f"ocai 调用失败：\n{output}"
    except subprocess.TimeoutExpired:
        print("[OCAI] 调用超时")
        return "ocai 处理超时。"
    except FileNotFoundError:
        print(f"[OCAI] 找不到命令: {AI_CMD}")
        return f"找不到 ocai 命令：{AI_CMD}"
    except Exception as e:
        print(f"[OCAI] 其他异常: {e}")
        return f"发生错误：{e}"
