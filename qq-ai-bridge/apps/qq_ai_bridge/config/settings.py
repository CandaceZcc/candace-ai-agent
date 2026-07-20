"""Runtime settings for the QQ AI bridge."""

import os
from pathlib import Path
from urllib.parse import urlparse


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[CONFIG] invalid int env {name}={raw!r}, fallback={default}")
        return default


def _get_bool_env(name: str, default: bool) -> bool:
    raw = os.getenv(name, "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "yes", "on"}:
        return True
    if raw in {"0", "false", "no", "off"}:
        return False
    print(f"[CONFIG] invalid bool env {name}={raw!r}, fallback={default}")
    return default


def _get_csv_env(name: str, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _get_int_set_env(name: str, default: tuple[int, ...] = ()) -> set[int]:
    values = _get_csv_env(name, tuple(str(v) for v in default))
    parsed: set[int] = set()
    for item in values:
        try:
            parsed.add(int(item))
        except ValueError:
            print(f"[CONFIG] invalid int list item {name}={item!r}, skipped")
    return parsed


def _resolve_project_path(raw_value: str, fallback_relative: str) -> str:
    """
    Resolve path env vars relative to qq-ai-bridge root by default.
    This avoids cwd-dependent config/data paths after restart.
    """
    value = (raw_value or "").strip()
    if not value:
        return str((QQ_AI_BRIDGE_ROOT / fallback_relative).resolve())
    candidate = Path(value).expanduser()
    if candidate.is_absolute():
        return str(candidate.resolve())
    return str((QQ_AI_BRIDGE_ROOT / candidate).resolve())


NAPCAT_HTTP = os.getenv("NAPCAT_HTTP", "http://127.0.0.1:3001").strip() or "http://127.0.0.1:3001"
NAPCAT_TOKEN = os.getenv("NAPCAT_TOKEN", "hajimi").strip() or "hajimi"
ALLOWED_PRIVATE_USER = _get_int_env("ALLOWED_PRIVATE_USER", 273007866)
OWNER_QQ = _get_int_env("OWNER_QQ", ALLOWED_PRIVATE_USER)
OWNER_NAME = os.getenv("OWNER_NAME", "Candace").strip() or "Candace"
AI_CMD = os.getenv("AI_CMD", "/home/cancade/.local/bin/ocai").strip() or "/home/cancade/.local/bin/ocai"
RUNTIME_CHAT_WORKERS = max(1, _get_int_env("RUNTIME_CHAT_WORKERS", 8))
RUNTIME_CHAT_MAX_PENDING = max(0, _get_int_env("RUNTIME_CHAT_MAX_PENDING", 64))
RUNTIME_MEDIA_WORKERS = max(1, _get_int_env("RUNTIME_MEDIA_WORKERS", 2))
RUNTIME_MEDIA_MAX_PENDING = max(0, _get_int_env("RUNTIME_MEDIA_MAX_PENDING", 8))
RUNTIME_SCHEDULED_MAX_PENDING = max(1, _get_int_env("RUNTIME_SCHEDULED_MAX_PENDING", 256))
CHAT_STATE_TTL_SECONDS = max(60, _get_int_env("CHAT_STATE_TTL_SECONDS", 1800))
IMAGE_CAPTION_PENDING_MAX = max(1, _get_int_env("IMAGE_CAPTION_PENDING_MAX", 128))

QQ_AI_BRIDGE_ROOT = Path(__file__).resolve().parents[3]
REPO_ROOT = QQ_AI_BRIDGE_ROOT.parent

MAX_REPLY_LEN = 1500
MAX_FILE_CONTENT_LEN = 8000

BASE_DATA_DIR = _resolve_project_path(os.getenv("BASE_DATA_DIR", ""), "data")
PRIVATE_UPLOAD_DIR = os.path.join(BASE_DATA_DIR, "private_uploads")
GROUP_UPLOAD_DIR = os.path.join(BASE_DATA_DIR, "group_uploads")
PRIVATE_USERS_DIR = os.path.join(BASE_DATA_DIR, "private_users")
GROUP_DATA_DIR = os.path.join(BASE_DATA_DIR, "groups")
BROWSER_AGENT_TASKS_PATH = os.path.join(BASE_DATA_DIR, "browser_agent_tasks.json")
CONFIG_DIR = _resolve_project_path(os.getenv("CONFIG_DIR", ""), "config")
GROUP_CONFIG_PATH = os.path.join(CONFIG_DIR, "groups.json")
IMAGE_TMP_DIR = _resolve_project_path(os.getenv("IMAGE_TMP_DIR", ""), "tmp/images")
REMINDERS_PATH = os.path.join(BASE_DATA_DIR, "reminders.json")
SCHEDULER_STATE_PATH = os.path.join(BASE_DATA_DIR, "scheduler_state.json")
SCHEDULE_PATH = os.path.join(BASE_DATA_DIR, "schedule.json")

SCHEDULER_TICK_SECONDS = max(1, _get_int_env("SCHEDULER_TICK_SECONDS", 15))
SLEEP_REMINDER_TIME = os.getenv("SLEEP_REMINDER_TIME", "01:30").strip() or "01:30"
TOMORROW_SCHEDULE_TIME = os.getenv("TOMORROW_SCHEDULE_TIME", "23:30").strip() or "23:30"
SLEEP_REMINDER_TEXT = os.getenv("SLEEP_REMINDER_TEXT", "该睡觉了，别熬太晚。").strip() or "该睡觉了，别熬太晚。"
SLEEP_REMINDER_TEST_DELAY_MINUTES = max(0, _get_int_env("SLEEP_REMINDER_TEST_DELAY_MINUTES", 0))
TOMORROW_SCHEDULE_TEST_DELAY_MINUTES = max(0, _get_int_env("TOMORROW_SCHEDULE_TEST_DELAY_MINUTES", 0))
PRIVATE_CONTEXT_WINDOW_SECONDS = max(60, _get_int_env("PRIVATE_CONTEXT_WINDOW_SECONDS", 1800))
PRIVATE_CONTEXT_SOFT_LIMIT_SECONDS = max(
    PRIVATE_CONTEXT_WINDOW_SECONDS,
    _get_int_env("PRIVATE_CONTEXT_SOFT_LIMIT_SECONDS", 3600),
)
PRIVATE_COMPACT_MAX_TURNS = max(1, _get_int_env("PRIVATE_COMPACT_MAX_TURNS", 2))
PRIVATE_COMPACT_MAX_CHARS = max(80, _get_int_env("PRIVATE_COMPACT_MAX_CHARS", 400))
PRIVATE_DEBOUNCE_MS = max(0, _get_int_env("PRIVATE_DEBOUNCE_MS", 3000))
PRIVATE_REPLY_COOLDOWN_SEC = max(0, _get_int_env("PRIVATE_REPLY_COOLDOWN_SEC", 8))
PRIVATE_COOLDOWN_MODE = os.getenv("PRIVATE_COOLDOWN_MODE", "record_only").strip().lower() or "record_only"
DEFAULT_WEATHER_LOCATION = (
    os.getenv("DEFAULT_WEATHER_LOCATION", os.getenv("DEFAULT_WEATHER_CITY", "Zhuhai")).strip() or "Zhuhai"
)
WEATHER_API_TIMEOUT_SECONDS = max(3, _get_int_env("WEATHER_API_TIMEOUT_SECONDS", 8))
WEATHER_ENABLE_LLM_LOCATION_FALLBACK = _get_bool_env("WEATHER_ENABLE_LLM_LOCATION_FALLBACK", True)

TEXT_LIKE_EXTS = (
    ".md", ".txt", ".json", ".jsonl", ".yaml", ".yml", ".toml", ".ini", ".cfg",
    ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".c", ".cpp", ".h",
    ".hpp", ".rs", ".go", ".php", ".rb", ".sh", ".zsh", ".bash", ".sql",
    ".html", ".htm", ".css", ".scss", ".xml", ".csv", ".tsv", ".log"
)

OFFICE_XML_EXTS = (".docx", ".pptx", ".xlsx")

MAX_ARCHIVE_LISTING = 40
MAX_ARCHIVE_PREVIEW_FILES = 5

PC_AGENT_URL = "http://127.0.0.1:5050"
BROWSER_AGENT_HTTP_TIMEOUT_SECONDS = max(3, _get_int_env("BROWSER_AGENT_HTTP_TIMEOUT_SECONDS", 12))
BROWSER_AGENT_MAX_TASKS = max(5, _get_int_env("BROWSER_AGENT_MAX_TASKS", 30))
BROWSER_AGENT_MAX_STEPS = max(3, _get_int_env("BROWSER_AGENT_MAX_STEPS", 8))
BROWSER_AGENT_MAX_REPEAT_ACTIONS = max(1, _get_int_env("BROWSER_AGENT_MAX_REPEAT_ACTIONS", 2))
AGENT_MAX_ITERATIONS = 6
AGENT_MAX_HISTORY = 8
AGENT_MAX_OCR_CHARS = 1200
AGENT_MAX_REPEAT_WORKFLOW = 2
AGENT_CONTINUE_COMMANDS = {"继续", "继续执行", "继续任务", "继续做", "继续查", "继续找"}
AGENT_CANCEL_COMMANDS = {"取消", "停止", "结束", "结束任务", "取消任务"}
AGENT_SESSION_MEMORY = {}
ALLOWED_ACTIONS = {
    "click",
    "move",
    "scroll",
    "type",
    "press",
    "hotkey",
    "wait",
    "screenshot",
    "position",
    "screen_size",
    "launch_and_open",
    "ocr",
    "find_text",
    "click_text"
}

AGENT_SYSTEM_PROMPT = """
你是一个桌面操作规划 AI。

把用户指令转换为 JSON workflow。

返回格式：
{
  "reply": "对用户说的话",
  "done": false,
  "actions": [
    {"action":"xxx","params":{}}
  ]
}

允许的 action:
- screenshot
- position
- screen_size
- ocr
- click
- move
- scroll
- type
- press
- hotkey
- wait
- launch_and_open
- find_text
- click_text

示例：
{"reply":"我将打开B站并搜索电棍。","actions":[
  {"action":"launch_and_open","params":{"url":"https://www.bilibili.com"}},
  {"action":"wait","params":{"seconds":2.5}},
  {"action":"hotkey","params":{"keys":["ctrl","l"]}},
  {"action":"type","params":{"text":"电棍"}},
  {"action":"press","params":{"key":"enter"}}
]}

{"reply":"我会尝试点击登录。","actions":[
  {"action":"click_text","params":{"text":"登录"}}
]}

{"reply":"我看到页面上有 Sign in，我会先点击它再继续。","actions":[
  {"action":"click_text","params":{"texts":["Sign in","SIGN IN","登录"]}},
  {"action":"wait","params":{"seconds":2}}
]}

{"reply":"我会先查看当前屏幕内容。","actions":[
  {"action":"ocr","params":{}}
]}

{"reply":"如果当前页面没看到目标，我会向下滚动后继续查找。","actions":[
  {"action":"scroll","params":{"clicks":-700,"method":"keys"}},
  {"action":"wait","params":{"seconds":1.5}},
  {"action":"ocr","params":{}}
]}

{"reply":"这个任务无法安全执行。","done":true,"actions":[]}

规则：
1. 只返回 JSON
2. 不要 markdown
3. 可以返回多个 action
4. actions 按顺序执行
5. 如果任务无法完成，actions 为空
6. 不要生成 shell、文件删除、系统设置、关机、剪贴板读取相关动作
7. launch_and_open 只在用户明确要求打开某个网站时使用
8. 登录类任务如果浏览器已保存登录状态，可以直接打开目标站点；如果必须人工介入，在 reply 里说明
9. 你会收到 task、latest_user_command、last_ocr_text、recent_results 这些上下文，必须结合它们规划下一步
10. 如果任务已经完成，或者必须等待用户下一次输入，返回 done=true 且 actions=[]
11. 优先使用 click_text、find_text、ocr 这类与当前屏幕内容相关的动作，而不是猜测固定坐标
12. 打开网站后通常先 wait 1 到 3 秒，再 screenshot 或 ocr
13. 如果 last_ocr_text 里出现 Sign in、Sign in with SSO、登录、统一身份认证、iSpace 之类文字，要据此决定下一步；看到 Sign in 或 登录 时，优先 click_text，而不是停住
14. 对登录按钮、认证入口、菜单项，优先用短词候选列表。例如 {"action":"click_text","params":{"texts":["Sign in","SIGN IN","Enterprise WeChat","WeChat","登录"]}}
15. 如果当前页面已经进入课程或 Dashboard，但没有看到 due、assignment、作业、deadline、Timeline 等目标，优先 scroll 后继续 ocr / find_text
16. 允许连续多步鼠标操作，不要因为已经点击过一次就立刻结束任务
17. 在浏览器页面里，scroll 优先使用 {"action":"scroll","params":{"clicks":-700,"method":"keys"}}，这样通常比鼠标滚轮更稳定
"""

BROWSER_AGENT_LOOP_PROMPT = """
你是一个本地浏览器 Agent 规划器。你只能为当前浏览器页面生成下一步 JSON 动作。

返回格式：
{
  "reply": "给用户的简短进度说明",
  "done": false,
  "actions": [
    {"action":"xxx","params":{}}
  ]
}

允许的 action:
- open_url
- click_text
- find_text
- ocr
- extract_deadline
- wait
- scroll

规则：
1. 只返回 JSON，不要 markdown。
2. 每次最多返回 2 个 action。
3. 优先 extract_deadline、click_text、find_text，不要猜固定坐标。
4. 如果已经看到 deadline / ddl / due / assignment / 作业 / 截止 信息，优先 extract_deadline。
5. 如果明显处于登录、统一身份认证、SSO、验证码、人机验证页面，必须 done=true 且 actions=[]，并在 reply 里要求人工接管。
6. 如果最近动作重复且页面几乎没变化，不要继续重复；done=true 并说明卡住位置。
7. 对 portal / moodle / ispace / dashboard / assignment 这类校园门户，可以合理点击 Sign in、登录、Course、Assignments、Timeline、Dashboard。
8. 如果当前还没打开目标网站，并且 task 里包含明确 URL 或域名，可以先 open_url。
9. 如果任务已经完成，返回 done=true 且 actions=[]。
"""

KIMI_API_KEY = os.getenv("KIMI_API_KEY", "").strip()
KIMI_BASE_URL = (
    os.getenv("KIMI_BASE_URL", "https://api.deepseek.com").strip()
    or "https://api.deepseek.com"
)
KIMI_MODEL = (
    os.getenv("KIMI_MODEL", "deepseek-v4-flash").strip() or "deepseek-v4-flash"
)
KIMI_TIMEOUT_SECONDS = max(5, _get_int_env("KIMI_TIMEOUT_SECONDS", 25))
LLM_BACKEND = os.getenv("LLM_BACKEND", "auto").strip().lower() or "auto"
if LLM_BACKEND not in {"auto", "direct", "cli"}:
    print(f"[CONFIG] invalid LLM_BACKEND={LLM_BACKEND!r}, fallback='auto'")
    LLM_BACKEND = "auto"
LLM_MAX_CONCURRENCY = max(1, _get_int_env("LLM_MAX_CONCURRENCY", 4))
LLM_QUEUE_TIMEOUT_SECONDS = max(0, _get_int_env("LLM_QUEUE_TIMEOUT_SECONDS", 1))

AGENT_PROVIDER_VALUES = {"openai", "responses_proxy", "chat_compatible"}
_RAW_AGENT_PROVIDER = os.getenv("AGENT_PROVIDER", "openai").strip().lower() or "openai"
_AGENT_PROVIDER_IS_VALID = _RAW_AGENT_PROVIDER in AGENT_PROVIDER_VALUES
AGENT_PROVIDER = _RAW_AGENT_PROVIDER if _AGENT_PROVIDER_IS_VALID else "openai"
AGENT_RUNTIME_ENABLED = _get_bool_env("AGENT_RUNTIME_ENABLED", False) and _AGENT_PROVIDER_IS_VALID
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
OPENAI_AGENT_MODEL = os.getenv("OPENAI_AGENT_MODEL", "gpt-5.6").strip() or "gpt-5.6"
OPENAI_HOSTED_WEB_SEARCH_ENABLED = _get_bool_env("OPENAI_HOSTED_WEB_SEARCH_ENABLED", False)
OPENAI_COMPUTER_USE_ENABLED = _get_bool_env("OPENAI_COMPUTER_USE_ENABLED", False)
RESPONSES_PROXY_API_KEY = os.getenv("RESPONSES_PROXY_API_KEY", "").strip()
RESPONSES_PROXY_BASE_URL = os.getenv("RESPONSES_PROXY_BASE_URL", "").strip()
RESPONSES_PROXY_MODEL = os.getenv("RESPONSES_PROXY_MODEL", "").strip()
CHAT_COMPATIBLE_API_KEY = os.getenv("CHAT_COMPATIBLE_API_KEY", "").strip()
CHAT_COMPATIBLE_BASE_URL = os.getenv("CHAT_COMPATIBLE_BASE_URL", "").strip()
CHAT_COMPATIBLE_MODEL = os.getenv("CHAT_COMPATIBLE_MODEL", "").strip()
AGENT_PROVIDER_CAPABILITY_STRICT = _get_bool_env("AGENT_PROVIDER_CAPABILITY_STRICT", True)
_AGENT_RAW_LIMIT_VALUES = {
    "AGENT_MAX_TURNS": os.getenv("AGENT_MAX_TURNS", "").strip(),
    "AGENT_MAX_TOOL_CALLS": os.getenv("AGENT_MAX_TOOL_CALLS", "").strip(),
    "AGENT_RUN_TIMEOUT_SECONDS": os.getenv("AGENT_RUN_TIMEOUT_SECONDS", "").strip(),
}
AGENT_MAX_TURNS = min(12, max(1, _get_int_env("AGENT_MAX_TURNS", 6)))
AGENT_MAX_TOOL_CALLS = min(20, max(1, _get_int_env("AGENT_MAX_TOOL_CALLS", 8)))
AGENT_RUN_TIMEOUT_SECONDS = min(300, max(1, _get_int_env("AGENT_RUN_TIMEOUT_SECONDS", 90)))
AGENT_TRACE_EXPORT_ENABLED = _get_bool_env("AGENT_TRACE_EXPORT_ENABLED", False)
AGENT_FALLBACK_TO_LEGACY = _get_bool_env("AGENT_FALLBACK_TO_LEGACY", True)


def _secret_state(value: str) -> str:
    return "set" if str(value or "").strip() else "missing"


def _is_loopback_hostname(hostname: str | None) -> bool:
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _is_https_or_loopback_url(value: str) -> bool:
    parsed = urlparse(value)
    if parsed.scheme == "https" and parsed.netloc:
        return True
    if parsed.scheme == "http" and _is_loopback_hostname(parsed.hostname):
        return True
    return False


def _validate_required(value: str, name: str, errors: list[str]) -> None:
    if not str(value or "").strip():
        errors.append(f"{name} is required")


def _validate_url(value: str, name: str, errors: list[str]) -> None:
    if value and not _is_https_or_loopback_url(value):
        errors.append(f"{name} must use https or a loopback http URL")


def _validate_positive_int_env(name: str, errors: list[str]) -> None:
    raw = _AGENT_RAW_LIMIT_VALUES.get(name, "")
    if not raw:
        return
    try:
        value = int(raw)
    except ValueError:
        errors.append(f"{name} must be a positive integer")
        return
    if value <= 0:
        errors.append(f"{name} must be a positive integer")


def validate_agent_settings() -> list[str]:
    """Return safe validation errors; never include credential values."""
    errors: list[str] = []
    if not _AGENT_PROVIDER_IS_VALID:
        errors.append(
            "AGENT_PROVIDER must be one of: chat_compatible, openai, responses_proxy"
        )

    _validate_positive_int_env("AGENT_MAX_TURNS", errors)
    _validate_positive_int_env("AGENT_MAX_TOOL_CALLS", errors)
    _validate_positive_int_env("AGENT_RUN_TIMEOUT_SECONDS", errors)

    if AGENT_PROVIDER == "chat_compatible" and OPENAI_HOSTED_WEB_SEARCH_ENABLED:
        errors.append("chat_compatible provider cannot use hosted web search")
    if AGENT_PROVIDER == "chat_compatible" and OPENAI_COMPUTER_USE_ENABLED:
        errors.append("chat_compatible provider cannot use built-in computer use")

    _validate_url(RESPONSES_PROXY_BASE_URL, "RESPONSES_PROXY_BASE_URL", errors)
    _validate_url(CHAT_COMPATIBLE_BASE_URL, "CHAT_COMPATIBLE_BASE_URL", errors)

    if not AGENT_RUNTIME_ENABLED:
        return errors

    if AGENT_PROVIDER == "openai":
        _validate_required(OPENAI_API_KEY, "OPENAI_API_KEY", errors)
    elif AGENT_PROVIDER == "responses_proxy":
        _validate_required(RESPONSES_PROXY_BASE_URL, "RESPONSES_PROXY_BASE_URL", errors)
        _validate_required(RESPONSES_PROXY_API_KEY, "RESPONSES_PROXY_API_KEY", errors)
        _validate_required(RESPONSES_PROXY_MODEL, "RESPONSES_PROXY_MODEL", errors)
    elif AGENT_PROVIDER == "chat_compatible":
        _validate_required(CHAT_COMPATIBLE_BASE_URL, "CHAT_COMPATIBLE_BASE_URL", errors)
        _validate_required(CHAT_COMPATIBLE_API_KEY, "CHAT_COMPATIBLE_API_KEY", errors)
        _validate_required(CHAT_COMPATIBLE_MODEL, "CHAT_COMPATIBLE_MODEL", errors)

    return errors


def agent_config_summary() -> dict[str, object]:
    """Return provider, models, flags, and secret set/missing states only."""
    return {
        "runtime_enabled": AGENT_RUNTIME_ENABLED,
        "provider": AGENT_PROVIDER,
        "provider_valid": _AGENT_PROVIDER_IS_VALID,
        "models": {
            "openai": OPENAI_AGENT_MODEL,
            "responses_proxy": RESPONSES_PROXY_MODEL,
            "chat_compatible": CHAT_COMPATIBLE_MODEL,
        },
        "capabilities": {
            "hosted_web_search_enabled": OPENAI_HOSTED_WEB_SEARCH_ENABLED,
            "computer_use_enabled": OPENAI_COMPUTER_USE_ENABLED,
            "strict": AGENT_PROVIDER_CAPABILITY_STRICT,
        },
        "limits": {
            "max_turns": AGENT_MAX_TURNS,
            "max_tool_calls": AGENT_MAX_TOOL_CALLS,
            "timeout_seconds": AGENT_RUN_TIMEOUT_SECONDS,
        },
        "secrets": {
            "openai_api_key": _secret_state(OPENAI_API_KEY),
            "responses_proxy_api_key": _secret_state(RESPONSES_PROXY_API_KEY),
            "chat_compatible_api_key": _secret_state(CHAT_COMPATIBLE_API_KEY),
        },
        "trace_export_enabled": AGENT_TRACE_EXPORT_ENABLED,
        "fallback_to_legacy": AGENT_FALLBACK_TO_LEGACY,
        "validation_errors": validate_agent_settings(),
    }

DRAW_API_KEY = (
    os.getenv("DRAW_API_KEY", "").strip()
    or os.getenv("VISION_API_KEY", "").strip()
)
DRAW_BASE_URL = (
    os.getenv("DRAW_BASE_URL", "https://www.right.codes").strip()
    or "https://www.right.codes"
)
DRAW_MODEL = os.getenv("DRAW_MODEL", "nano-banana-2").strip() or "nano-banana-2"
DRAW_ASPECT_RATIO = os.getenv("DRAW_ASPECT_RATIO", "1:1").strip() or "1:1"
DRAW_IMAGE_SIZE = os.getenv("DRAW_IMAGE_SIZE", "1K").strip() or "1K"
DRAW_POLL_INTERVAL_SECONDS = max(0, _get_int_env("DRAW_POLL_INTERVAL_SECONDS", 2))
DRAW_TIMEOUT_SECONDS = max(1, _get_int_env("DRAW_TIMEOUT_SECONDS", 240))
DRAW_POLL_MAX_TRANSIENT_ERRORS = max(
    0,
    _get_int_env("DRAW_POLL_MAX_TRANSIENT_ERRORS", 6),
)
DRAW_FALLBACK_MODEL = (
    os.getenv("DRAW_FALLBACK_MODEL", "gpt-image-2").strip()
    or "gpt-image-2"
)
DRAW_FALLBACK_ENABLED = _get_bool_env("DRAW_FALLBACK_ENABLED", True)

VOCAT_WEBHOOK_TOKEN = os.getenv("VOCAT_WEBHOOK_TOKEN", "").strip()
VOCAT_API_TOKEN = os.getenv("VOCAT_API_TOKEN", "").strip()
VOCAT_EXPRESSION_API_URL = os.getenv("VOCAT_EXPRESSION_API_URL", "").strip()
VOCAT_TTS_API_URL = os.getenv("VOCAT_TTS_API_URL", "").strip()
VOCAT_INSTANCE_ID = os.getenv("VOCAT_INSTANCE_ID", "").strip()
VOCAT_PRODUCT_KEY = os.getenv("VOCAT_PRODUCT_KEY", "").strip()
VOCAT_DEVICE_NAME = os.getenv("VOCAT_DEVICE_NAME", "").strip()
VOCAT_BOT_ID = os.getenv("VOCAT_BOT_ID", "").strip()
VOCAT_CONTROL_TIMEOUT_SECONDS = max(3, _get_int_env("VOCAT_CONTROL_TIMEOUT_SECONDS", 15))
VOCAT_QQ_FORWARD_USER_ID = _get_int_env("VOCAT_QQ_FORWARD_USER_ID", OWNER_QQ)
VOCAT_REMOTE_CONTROL_USERS = _get_int_set_env("VOCAT_REMOTE_CONTROL_USERS", (OWNER_QQ,))
VOCAT_QQ_KEYWORDS = set(_get_csv_env("VOCAT_QQ_KEYWORDS", ("qq", "QQ", "发QQ", "转发QQ", "告诉QQ")))
VOCAT_VOICE_REPLY_TO_QQ = _get_bool_env("VOCAT_VOICE_REPLY_TO_QQ", True)
VOCAT_QQ_REPLY_TO_DEVICE = _get_bool_env("VOCAT_QQ_REPLY_TO_DEVICE", True)
VOCAT_DAILY_BROADCAST_TO_DEVICE = _get_bool_env("VOCAT_DAILY_BROADCAST_TO_DEVICE", True)
VOCAT_COMMAND_QUEUE_MAX = max(1, _get_int_env("VOCAT_COMMAND_QUEUE_MAX", 50))
VOCAT_TRUSTED_DEVICE_IPS = set(_get_csv_env("VOCAT_TRUSTED_DEVICE_IPS", ("192.168.110.200",)))
VOCAT_MD_ROOT = Path(
    os.getenv("VOCAT_MD_ROOT", str(QQ_AI_BRIDGE_ROOT)).strip() or str(QQ_AI_BRIDGE_ROOT)
).expanduser()
VOCAT_SKILL_TIMEOUT_SECONDS = max(2, _get_int_env("VOCAT_SKILL_TIMEOUT_SECONDS", 8))

# Group routing policy
GLOBAL_LISTEN_GROUP_IDS = _get_int_set_env("GLOBAL_LISTEN_GROUP_IDS", (1065429760,))
VISION_GROUP_COOLDOWN_SECONDS = max(0, _get_int_env("VISION_GROUP_COOLDOWN_SECONDS", 45))
VISION_GROUP_PASSIVE_READ_INTERVAL_SECONDS = max(
    0,
    _get_int_env("VISION_GROUP_PASSIVE_READ_INTERVAL_SECONDS", 180),
)
