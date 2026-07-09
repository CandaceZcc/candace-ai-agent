"""QQ emoji helpers.

Reference:
- Moonlark uses a QQ emoji id-name mapping in `qq_emoji.json`.
"""

from __future__ import annotations

import json
import random
import re

from shared.ai.llm_client import call_ai

# Keep aliases close to QQ / Moonlark naming so explicit user requests resolve well.
QQ_EMOJI_NAME_TO_ID: dict[str, int] = {
    "笑哭": 182,
    "泪奔": 173,
    "捂脸": 264,
    "doge": 179,
    "Doge": 179,
    "棒棒糖": 147,
    "西瓜": 89,
    "尴尬": 10,
    "惊讶": 0,
    "爱心": 66,
    "点赞": 201,
    "赞": 76,
    "问号": 268,
    "问号脸": 268,
    "疑问": 32,
    "吃瓜": 271,
    "哦": 287,
    "呵呵哒": 272,
    "无奈": 174,
    "舔屏": 339,
    "/舔屏": 339,
    "续标识": 424,
    "/续标识": 424,
    "按按钮": 424,
    "按钮": 424,
    "红按钮": 424,
    "爆了": 424,
}

DEFAULT_EMOJI_SEQUENCE: tuple[str, ...] = ("笑哭", "棒棒糖", "西瓜", "尴尬", "惊讶", "舔屏", "续标识")
DEFAULT_REACTION_ORDER: tuple[str, ...] = (
    "button_marker",
    "lollipop",
    "watermelon",
    "awkward",
    "surprised",
    "red_button",
    "question",
    "laugh_cry",
    "lick_screen",
)
_EMOJI_REQUEST_PATTERN = re.compile(r"(贴|发|来个|来一个|给我).{0,4}(表情|emoji|face)")
_MESSAGE_REACTION_REQUEST_PATTERN = re.compile(r"(消息|这条|上面).{0,6}(贴|点|react).{0,6}(表情|emoji|face)")
_EMOJI_COUNT_PATTERN = re.compile(r"(几|[0-9]{1,2}|[一二两三四五六])\s*(个|次|条)?")
_ZH_NUM_MAP = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6}
_POLITICAL_SENSITIVE_PATTERN = re.compile(
    r"(8964|64学运|坦克人|天安门|维尼|包包|庆丰|乳包|乳化|习近平|共产党|中共|毛左|文革|六四|"
    r"李老师|冲塔|反贼|政治|敏感词|政治敏感|维权|上访|言论自由|翻墙|晶哥|建政|键政|赢麻|"
    r"粉红|神友|浪人|支黑|兔友|境外势力|塔|老大哥|铁拳|献忠|张献忠|图纸|屠支|恨国|爱国大V|"
    r"台湾|台独|港独|疆独|藏独|香港|新疆|西藏|法轮功|轮子|民主|自由派|左派|右派|纳粹|法西斯)"
)
_CONTROVERSIAL_PATTERN = re.compile(
    r"(女权|男权|彩礼|婚驴|LGBT|lgbt|跨性别|同性恋|巴以|巴勒斯坦|以色列|哈马斯|乌克兰|俄罗斯|台海|"
    r"民粹|地域黑|厌女|厌男|饭圈|极端|争议|吵翻|站队|对线|开团|炎上|挂人|网暴|盒武器|开盒|"
    r"男女对立|娇妻|龟男|田园女权|拳师|仙女|小仙女|incel|性别对立|学历歧视|地域歧视|"
    r"黑命贵|白左|移民|难民|宗教|穆斯林|基督教|犹太|印度|日本|韩国|仇日|仇韩|歧视)"
)
_SEXUAL_PATTERN = re.compile(
    r"(色|涩|性|骚|烧|想冲|冲了|发情|发骚|做爱|操|口|乳|胸|屁股|腿玩年|好顶|好想舔|舔一口|"
    r"舔屏|老公|老婆|斯哈|想日|精液|射了|性癖|媚|想透|想草|鸡巴|几把|屌|牛子|跳蛋|自慰|手冲|"
    r"黄图|涩图|擦边|瑟瑟|色色|开车|车牌|本子|裸|裸体|裸照|奶子|欧派|内裤|黑丝|白丝|足控|"
    r"榨精|高潮|插入|透批|约炮|炮友|性骚扰|想妈妈了)"
)
_LLM_REACTION_HINT_PATTERN = re.compile(
    r"(政治|敏感|争议|吵|逆天|抽象|恶心|爆了|炎上|开团|对线|离谱|绷不住|麻了|典|典中典|"
    r"地狱笑话|暴论|锐评|节奏|挂人|开盒|盒武器|色|涩|骚|烧|舔|擦边|开车)"
)


def _normalize_reaction_name(name: str) -> str:
    normalized = str(name or "").strip().lower()
    alias_map = {
        "laugh_cry": "laugh_cry",
        "笑哭": "laugh_cry",
        "red_button": "red_button",
        "button_marker": "button_marker",
        "爱心": "red_button",
        "按钮": "button_marker",
        "红按钮": "button_marker",
        "按按钮": "button_marker",
        "红心": "red_button",
        "lollipop": "lollipop",
        "棒棒糖": "lollipop",
        "watermelon": "watermelon",
        "西瓜": "watermelon",
        "awkward": "awkward",
        "尴尬": "awkward",
        "surprised": "surprised",
        "惊讶": "surprised",
        "lick_screen": "lick_screen",
        "舔屏": "lick_screen",
        "/舔屏": "lick_screen",
        "explode_marker": "explode_marker",
        "爆了": "explode_marker",
        "续标识": "button_marker",
        "/续标识": "button_marker",
        "question": "question",
        "问号": "question",
    }
    return alias_map.get(normalized, "")


def infer_reaction_preferred_order(text: str, default_order: tuple[str, ...] = DEFAULT_REACTION_ORDER) -> tuple[str, ...]:
    normalized = str(text or "").strip()
    if not normalized:
        return default_order

    first_choice = ""
    if _POLITICAL_SENSITIVE_PATTERN.search(normalized) or _CONTROVERSIAL_PATTERN.search(normalized):
        first_choice = "button_marker"
    elif _SEXUAL_PATTERN.search(normalized):
        first_choice = "lick_screen"
    else:
        explicit_choice = _infer_explicit_reaction_name(normalized)
        if explicit_choice:
            first_choice = explicit_choice
        elif any(token in normalized for token in ("晚安", "睡觉了", "睡了", "困了", "先睡")):
            first_choice = "lollipop"
        elif any(token in normalized for token in ("?", "？", "吗", "怎么", "为什么", "啥", "什么")):
            first_choice = "question"
        elif any(token in normalized for token in ("尴尬", "无语", "蚌埠住", "绷不住")):
            first_choice = "awkward"
        elif is_message_reaction_request(normalized):
            first_choice = "button_marker"
        elif _LLM_REACTION_HINT_PATTERN.search(normalized):
            first_choice = _infer_reaction_with_llm(normalized)

    if not first_choice:
        return default_order
    return tuple(dict.fromkeys((first_choice,) + tuple(default_order)))


def _infer_explicit_reaction_name(text: str) -> str:
    explicit_aliases = {
        "button_marker": ("button_marker", "红按钮", "按按钮", "按钮", "续标识"),
        "red_button": ("red_button", "红心", "爱心"),
        "laugh_cry": ("laugh_cry", "笑哭", "绷不住"),
        "lollipop": ("lollipop", "棒棒糖"),
        "watermelon": ("watermelon", "西瓜"),
        "awkward": ("awkward", "尴尬"),
        "surprised": ("surprised", "惊讶", "震惊"),
        "lick_screen": ("lick_screen", "舔屏"),
        "explode_marker": ("explode_marker", "爆了", "炸裂"),
        "question": ("question", "问号", "疑问"),
    }
    lowered = text.lower()
    for reaction_name, aliases in explicit_aliases.items():
        if any(alias.lower() in lowered for alias in aliases):
            return reaction_name
    return ""


def _infer_reaction_with_llm(text: str) -> str:
    if _POLITICAL_SENSITIVE_PATTERN.search(text) or _CONTROVERSIAL_PATTERN.search(text):
        return "button_marker"
    if _SEXUAL_PATTERN.search(text):
        return "lick_screen"

    prompt = (
        "你是 QQ 群聊表情 reaction 选择器，只输出 JSON。\n"
        "从这几个候选里选最贴切的一个："
        "laugh_cry, button_marker, red_button, lollipop, watermelon, awkward, surprised, lick_screen, question。\n"
        "规则：\n"
        "1) 中国政治敏感内容、谐音梗政治影射、容易引战的争议话题 -> button_marker。\n"
        "2) 性暗示、性喜欢、骚话、故意恶心群友 -> lick_screen。\n"
        "3) 普通好笑、绷不住 -> laugh_cry。\n"
        "4) 抽象、逆天、炸裂、麻了、炎上、开团、对线 -> button_marker。\n"
        "5) 只输出 JSON: {\"emoji\":\"...\"}\n"
        f"文本：{text[:160]}"
    )
    raw = call_ai(
        prompt,
        metadata={
            "user_id": "emoji_selector",
            "prompt_mode": "emoji_reaction_selector",
            "query_len": len(text),
        },
    )
    candidate = str(raw or "").strip()
    if "{" in candidate and "}" in candidate:
        candidate = candidate[candidate.find("{") : candidate.rfind("}") + 1]
    try:
        payload = json.loads(candidate)
        emoji_name = _normalize_reaction_name(payload.get("emoji", ""))
        if emoji_name:
            if emoji_name == "explode_marker":
                return "button_marker"
            return emoji_name
    except Exception:
        pass
    lowered = str(raw or "").lower()
    for token in (
        "explode_marker",
        "lick_screen",
        "laugh_cry",
        "button_marker",
        "red_button",
        "lollipop",
        "watermelon",
        "awkward",
        "surprised",
        "question",
    ):
        if token in lowered:
            if token == "explode_marker":
                return "button_marker"
            return token
    return ""


def is_emoji_request(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    if "贴表情" in normalized or "给我贴个表情" in normalized:
        return True
    return bool(_EMOJI_REQUEST_PATTERN.search(normalized))


def is_message_reaction_request(text: str) -> bool:
    normalized = str(text or "").strip().lower()
    if not normalized:
        return False
    return bool(_MESSAGE_REACTION_REQUEST_PATTERN.search(normalized))


def is_face_fallback_request(text: str) -> bool:
    normalized = str(text or "").strip()
    if not normalized:
        return False
    if not extract_emoji_name(normalized):
        return False
    return any(token in normalized for token in ("贴", "发", "来个", "来一个", "给我", "整", "要"))


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


def detect_emoji_request_count(text: str, default_count: int = 1, max_count: int = 4) -> int:
    normalized = str(text or "").strip()
    if not normalized:
        return default_count
    m = _EMOJI_COUNT_PATTERN.search(normalized)
    if not m:
        return default_count
    token = m.group(1)
    if token == "几":
        return min(2, max_count)
    if token.isdigit():
        return min(max(int(token), 1), max_count)
    value = _ZH_NUM_MAP.get(token, default_count)
    return min(max(value, 1), max_count)


def build_face_sequence(seed: str, count: int, preferred: tuple[str, ...] = DEFAULT_EMOJI_SEQUENCE) -> list[str]:
    names = [name for name in preferred if name in QQ_EMOJI_NAME_TO_ID]
    if not names:
        names = list(QQ_EMOJI_NAME_TO_ID.keys())
    if not names:
        return ["[CQ:face,id=182]"]
    rng = random.Random(seed)
    order = names[:]
    rng.shuffle(order)
    result: list[str] = []
    for idx in range(max(1, count)):
        name = order[idx % len(order)]
        result.append(build_face_cq(name) or "[CQ:face,id=182]")
    return result


def build_emoji_id_sequence(seed: str, count: int, preferred: tuple[str, ...] = DEFAULT_EMOJI_SEQUENCE) -> list[str]:
    names = [name for name in preferred if name in QQ_EMOJI_NAME_TO_ID]
    if not names:
        names = list(QQ_EMOJI_NAME_TO_ID.keys())
    if not names:
        return ["182"]
    rng = random.Random(seed)
    order = names[:]
    rng.shuffle(order)
    result: list[str] = []
    for idx in range(max(1, count)):
        name = order[idx % len(order)]
        result.append(str(QQ_EMOJI_NAME_TO_ID.get(name, 182)))
    return result


__all__ = [
    "QQ_EMOJI_NAME_TO_ID",
    "build_face_sequence",
    "build_emoji_id_sequence",
    "build_face_cq",
    "detect_emoji_request_count",
    "extract_emoji_name",
    "is_face_fallback_request",
    "is_emoji_request",
    "is_message_reaction_request",
    "pick_face_cq",
]
