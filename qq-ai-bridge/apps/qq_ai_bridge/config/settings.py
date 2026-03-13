"""Runtime settings for the QQ AI bridge."""

import os


def _get_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        print(f"[CONFIG] invalid int env {name}={raw!r}, fallback={default}")
        return default


NAPCAT_HTTP = os.getenv("NAPCAT_HTTP", "http://127.0.0.1:3001").strip() or "http://127.0.0.1:3001"
NAPCAT_TOKEN = os.getenv("NAPCAT_TOKEN", "hajimi").strip() or "hajimi"
ALLOWED_PRIVATE_USER = _get_int_env("ALLOWED_PRIVATE_USER", 273007866)
OWNER_QQ = _get_int_env("OWNER_QQ", ALLOWED_PRIVATE_USER)
OWNER_NAME = os.getenv("OWNER_NAME", "Candace").strip() or "Candace"
AI_CMD = os.getenv("AI_CMD", "/home/cancade/.local/bin/ocai").strip() or "/home/cancade/.local/bin/ocai"

MAX_REPLY_LEN = 1500
MAX_FILE_CONTENT_LEN = 8000

BASE_DATA_DIR = os.getenv("BASE_DATA_DIR", "./data").strip() or "./data"
PRIVATE_UPLOAD_DIR = os.path.join(BASE_DATA_DIR, "private_uploads")
GROUP_UPLOAD_DIR = os.path.join(BASE_DATA_DIR, "group_uploads")
PRIVATE_USERS_DIR = os.path.join(BASE_DATA_DIR, "private_users")
GROUP_DATA_DIR = os.path.join(BASE_DATA_DIR, "groups")
CONFIG_DIR = os.getenv("CONFIG_DIR", "./config").strip() or "./config"
GROUP_CONFIG_PATH = os.path.join(CONFIG_DIR, "groups.json")
IMAGE_TMP_DIR = "./tmp/images"
REMINDERS_PATH = os.path.join(BASE_DATA_DIR, "reminders.json")
SCHEDULER_STATE_PATH = os.path.join(BASE_DATA_DIR, "scheduler_state.json")
SCHEDULE_PATH = os.path.join(BASE_DATA_DIR, "schedule.json")

SCHEDULER_TICK_SECONDS = max(1, _get_int_env("SCHEDULER_TICK_SECONDS", 15))
SLEEP_REMINDER_TIME = os.getenv("SLEEP_REMINDER_TIME", "01:30").strip() or "01:30"
TOMORROW_SCHEDULE_TIME = os.getenv("TOMORROW_SCHEDULE_TIME", "23:30").strip() or "23:30"
SLEEP_REMINDER_TEXT = os.getenv("SLEEP_REMINDER_TEXT", "该睡觉了，别熬太晚。").strip() or "该睡觉了，别熬太晚。"
SLEEP_REMINDER_TEST_DELAY_MINUTES = max(0, _get_int_env("SLEEP_REMINDER_TEST_DELAY_MINUTES", 0))
TOMORROW_SCHEDULE_TEST_DELAY_MINUTES = max(0, _get_int_env("TOMORROW_SCHEDULE_TEST_DELAY_MINUTES", 0))

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
