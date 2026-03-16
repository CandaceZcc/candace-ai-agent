"""Weather query helpers with layered Chinese location resolution."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

import requests

from apps.qq_ai_bridge.config.settings import (
    DEFAULT_WEATHER_LOCATION,
    WEATHER_API_TIMEOUT_SECONDS,
    WEATHER_ENABLE_LLM_LOCATION_FALLBACK,
)
from shared.ai.llm_client import call_ai


LOCAL_DEFAULT_QUERY_PATTERNS = (
    r"^今天天气如何$",
    r"^现在天气怎么样$",
    r"^今日天气$",
    r"^天气如何$",
    r"^这会儿天气如何$",
    r"^外面冷吗$",
    r"^现在冷吗$",
    r"^现在热吗$",
)

EXPLICIT_LOCATION_SUFFIXES = (
    "今天天气如何",
    "今日天气",
    "现在天气怎么样",
    "现在天气如何",
    "天气怎么样",
    "天气如何",
    "天气怎样",
    "今天天气",
    "现在天气",
    "weather",
    "天气",
    "现在冷吗",
    "冷吗",
    "现在热吗",
    "热吗",
)

DIRECT_MUNICIPALITIES = {"北京", "上海", "天津", "重庆"}
KNOWN_NON_CHINA_CJK_LOCATIONS = {"东京", "伦敦", "牛津", "大阪", "巴黎", "纽约", "首尔", "京都"}
CHONGQING_PRIORITY_TERMS = {
    "渝中",
    "江北",
    "南岸",
    "沙坪坝",
    "九龙坡",
    "大渡口",
    "北碚",
    "渝北",
    "巴南",
    "长寿",
    "江津",
    "合川",
    "永川",
    "南川",
    "綦江",
    "潼南",
    "铜梁",
    "大足",
    "荣昌",
    "璧山",
    "梁平",
    "开州",
    "城口",
    "丰都",
    "垫江",
    "武隆",
    "忠县",
    "云阳",
    "奉节",
    "巫山",
    "巫溪",
    "黔江",
    "石柱",
    "秀山",
    "酉阳",
    "彭水",
}

WEATHER_CODE_MAP = {
    0: "晴朗",
    1: "大致晴",
    2: "多云",
    3: "阴天",
    45: "有雾",
    48: "有雾",
    51: "小毛毛雨",
    53: "毛毛雨",
    55: "较强毛毛雨",
    61: "小雨",
    63: "中雨",
    65: "大雨",
    71: "小雪",
    73: "中雪",
    75: "大雪",
    80: "阵雨",
    81: "较强阵雨",
    82: "强阵雨",
    95: "雷暴",
}


@dataclass
class WeatherIntent:
    kind: str
    raw_location: str | None = None


@dataclass
class CnLocationNormalization:
    normalized_query: str
    candidate_queries: list[str]
    is_china_location: bool
    guessed_region_bias: str | None = None


@dataclass
class LocationResolutionResult:
    ok: bool
    requested_location: str
    resolved_location: str | None = None
    display_name: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    reason: str = ""


def is_weather_query(text: str) -> bool:
    return detect_weather_intent(text) is not None


def detect_weather_intent(text: str) -> WeatherIntent | None:
    normalized = re.sub(r"\s+", "", str(text or "")).strip()
    if not normalized:
        return None

    if any(re.match(pattern, normalized) for pattern in LOCAL_DEFAULT_QUERY_PATTERNS):
        return WeatherIntent(kind="local_default")

    explicit_location = _extract_explicit_location(normalized)
    if explicit_location:
        return WeatherIntent(kind="explicit_city", raw_location=explicit_location)
    return None


def query_weather_by_intent(intent: WeatherIntent) -> dict[str, Any]:
    if intent.kind == "local_default":
        print("[WEATHER] intent=local_default")
        return query_weather_for_location(DEFAULT_WEATHER_LOCATION)

    raw_location = str(intent.raw_location or "").strip()
    print(f"[WEATHER] intent=explicit_city raw_city={raw_location}")
    if not raw_location:
        return build_weather_error("暂时获取不到天气信息，请稍后再试。", reason="empty_raw_location")
    return query_weather_for_explicit_location(raw_location)


def query_weather_for_explicit_location(raw_location: str) -> dict[str, Any]:
    resolution = resolve_location(raw_location)
    if not resolution.ok or resolution.latitude is None or resolution.longitude is None:
        if resolution.reason in {"ambiguous_location", "low_confidence_geocoding_result", "no_geocoding_result"}:
            return build_weather_error(
                f"暂时无法准确定位“{raw_location}”，请尝试输入更完整地名，例如“{build_location_hint(raw_location)}”。",
                reason=resolution.reason,
                city=raw_location,
            )
        return build_weather_error(
            f"暂时获取不到“{raw_location}”的天气信息，请稍后再试。",
            reason=resolution.reason or "location_resolution_failed",
            city=raw_location,
        )

    print(f"[WEATHER] final location chosen={resolution.display_name or resolution.resolved_location or raw_location}")
    return query_weather_for_coordinates(
        requested_location=raw_location,
        display_name=resolution.display_name or resolution.resolved_location or raw_location,
        latitude=resolution.latitude,
        longitude=resolution.longitude,
    )


def query_weather_for_location(location: str) -> dict[str, Any]:
    print(f"[WEATHER] query location={location}")
    resolution = _resolve_by_candidates(normalize_cn_location(location))
    if not resolution.ok or resolution.latitude is None or resolution.longitude is None:
        return build_weather_error("暂时获取不到天气信息，请稍后再试。", reason=resolution.reason, city=location)
    print(f"[WEATHER] final location chosen={resolution.display_name or resolution.resolved_location or location}")
    return query_weather_for_coordinates(
        requested_location=location,
        display_name=resolution.display_name or resolution.resolved_location or location,
        latitude=resolution.latitude,
        longitude=resolution.longitude,
    )


def query_weather_for_coordinates(
    requested_location: str,
    display_name: str,
    latitude: float,
    longitude: float,
) -> dict[str, Any]:
    print(f"[WEATHER] query location={requested_location}")
    try:
        weather_resp = requests.get(
            "https://api.open-meteo.com/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,apparent_temperature,weather_code",
                "timezone": "Asia/Shanghai",
            },
            timeout=WEATHER_API_TIMEOUT_SECONDS,
        )
        weather_resp.raise_for_status()
        weather_data = weather_resp.json()
        current = weather_data.get("current", {})
        temp = current.get("temperature_2m")
        apparent = current.get("apparent_temperature")
        code = int(current.get("weather_code", -1))
        condition = WEATHER_CODE_MAP.get(code, "天气状况未知")
        print(f"[WEATHER] success temp={temp} condition={condition}")
        return {
            "ok": True,
            "city": display_name,
            "temperature": temp,
            "apparent_temperature": apparent,
            "condition": condition,
        }
    except Exception as exc:
        print(f"[WEATHER] failed error={exc}")
        return build_weather_error(
            f"暂时获取不到“{requested_location}”的天气信息，请稍后再试。",
            reason=str(exc),
            city=requested_location,
        )


def resolve_location(raw_location: str) -> LocationResolutionResult:
    normalization = normalize_cn_location(raw_location)
    rule_resolution = _resolve_by_candidates(normalization)
    if rule_resolution.ok:
        return rule_resolution

    if not WEATHER_ENABLE_LLM_LOCATION_FALLBACK:
        return rule_resolution

    resolved_city = resolve_location_with_llm(raw_location)
    if not resolved_city:
        print(f"[WEATHER] llm_location_failed raw_city={raw_location}")
        return LocationResolutionResult(ok=False, requested_location=raw_location, reason="ambiguous_location")

    print(f"[WEATHER] llm_fallback used raw={raw_location} resolved={resolved_city}")
    llm_normalization = normalize_cn_location(resolved_city)
    llm_resolution = _resolve_by_candidates(llm_normalization, original_raw=raw_location)
    if llm_resolution.ok:
        llm_resolution.requested_location = raw_location
        return llm_resolution
    return LocationResolutionResult(ok=False, requested_location=raw_location, reason=llm_resolution.reason or "ambiguous_location")


def normalize_cn_location(raw_city: str) -> CnLocationNormalization:
    cleaned = _normalize_location_text(raw_city)
    is_cn = _is_chinese_location(cleaned)
    guessed_region_bias: str | None = None
    candidates: list[str] = []

    if not cleaned:
        plan = CnLocationNormalization("", [], is_cn, guessed_region_bias)
        print(f"[WEATHER] normalize raw={raw_city} normalized={plan.normalized_query} candidates={plan.candidate_queries}")
        return plan

    if not is_cn:
        plan = CnLocationNormalization(cleaned, [cleaned], False, None)
        print(f"[WEATHER] normalize raw={raw_city} normalized={plan.normalized_query} candidates={plan.candidate_queries}")
        return plan

    base = _dedupe_direct_municipality(cleaned)
    district_term = _strip_municipality_prefix(base)

    municipality = _detect_municipality_prefix(base)

    if cleaned == "重庆" or base == "重庆":
        guessed_region_bias = "重庆"
        candidates.extend(["重庆市", "重庆 China", "重庆"])
    elif district_term in CHONGQING_PRIORITY_TERMS:
        guessed_region_bias = "重庆"
        district_full = district_term if district_term.endswith(("区", "县")) else f"{district_term}区"
        candidates.extend(
            [
                f"重庆市{district_full}",
                f"{district_full} 重庆",
                f"{district_term} 重庆",
                f"重庆 {district_term}",
            ]
        )
        if cleaned.startswith("重庆"):
            candidates.append(f"重庆市 {district_term}")
        candidates.append(district_term)
    elif municipality == "重庆":
        guessed_region_bias = "重庆"
        normalized_chongqing = _normalize_chongqing_expression(cleaned)
        district_piece = _strip_municipality_prefix(normalized_chongqing)
        candidates.extend(
            [
                normalized_chongqing,
                f"{district_piece} 重庆" if district_piece else normalized_chongqing,
                f"重庆 {district_piece}" if district_piece else normalized_chongqing,
            ]
        )
        if district_piece and district_piece != normalized_chongqing:
            candidates.append(district_piece)
    elif municipality:
        normalized_municipality = _normalize_municipality_expression(cleaned, municipality)
        district_piece = _strip_municipality_prefix(normalized_municipality)
        candidates.extend(
            [
                normalized_municipality,
                f"{district_piece} {municipality}" if district_piece else normalized_municipality,
                f"{municipality} {district_piece}" if district_piece else normalized_municipality,
            ]
        )
        if district_piece and district_piece != normalized_municipality:
            candidates.append(district_piece)
    else:
        candidates.append(cleaned)

    normalized_query = candidates[0] if candidates else cleaned
    deduped_candidates = _dedupe_keep_order([candidate for candidate in candidates if candidate])
    plan = CnLocationNormalization(normalized_query, deduped_candidates, True, guessed_region_bias)
    print(
        f"[WEATHER] normalize raw={raw_city}"
        f" normalized={plan.normalized_query}"
        f" candidates={plan.candidate_queries}"
    )
    return plan


def resolve_location_with_llm(raw_city: str) -> str | None:
    print(f"[WEATHER] llm_location_fallback raw_city={raw_city}")
    prompt = (
        "你是地点标准化助手。\n"
        "任务：把用户给出的模糊地点改写成更标准、适合地理编码查询的地点名。\n"
        "规则：\n"
        "1. 只输出一个标准地点名。\n"
        "2. 不要输出天气，不要解释，不要多余文字。\n"
        "3. 直辖市不要重复，例如输出“重庆市沙坪坝区”，不要输出“重庆重庆沙坪坝”。\n"
        "4. 对中国地名可补全到“省/市/区”，例如“永川”->“重庆市永川区”。\n"
        "5. 如果无法可靠判断，输出 UNKNOWN。\n\n"
        f"原始地点：{raw_city}"
    )
    output = call_ai(
        prompt,
        metadata={
            "user_id": "weather_resolver",
            "merged_message_count": 1,
            "prompt_mode": "weather_location_resolver",
            "query_len": len(raw_city),
            "history_chars": 0,
            "history_items": 0,
            "instruction_chars": len(prompt),
            "prompt_chars": len(prompt),
        },
    ).strip()
    cleaned = re.sub(r"[\r\n`]+", " ", output).strip().strip("。")
    if not cleaned or cleaned.upper() == "UNKNOWN":
        return None
    if "天气" in cleaned:
        return None
    return _normalize_location_text(cleaned)


def build_weather_reply(weather_result: dict[str, Any]) -> str:
    if not weather_result.get("ok"):
        return weather_result.get("message") or "暂时获取不到天气信息，请稍后再试。"

    city = weather_result["city"]
    temp = weather_result.get("temperature")
    apparent = weather_result.get("apparent_temperature")
    condition = weather_result.get("condition", "天气状况未知")
    if temp is None:
        return f"{city}当前天气信息不完整，请稍后再试。"

    comfort = "体感舒适，今晚出门问题不大。" if apparent is not None and 18 <= float(apparent) <= 28 else "注意根据体感温度调整穿着。"
    return f"{city}现在 {temp}°C，{condition}。\n{comfort}"


def build_weather_error(message: str, reason: str = "", city: str = "") -> dict[str, Any]:
    return {"ok": False, "error": reason, "city": city, "message": message}


def build_location_hint(raw_location: str) -> str:
    normalized = _normalize_location_text(raw_location)
    if not _is_chinese_location(normalized):
        return normalized or raw_location
    if normalized in DIRECT_MUNICIPALITIES:
        return f"{normalized}市"
    district_term = _strip_municipality_prefix(normalized)
    if district_term in CHONGQING_PRIORITY_TERMS:
        suffix = district_term if district_term.endswith(("区", "县")) else f"{district_term}区"
        return f"重庆市{suffix}"
    municipality = _detect_municipality_prefix(normalized)
    if municipality:
        if municipality == "重庆":
            district_piece = _strip_municipality_prefix(normalized)
            if district_piece and district_piece != "重庆":
                suffix = district_piece if district_piece.endswith(("区", "县")) else f"{district_piece}区"
                return f"重庆市{suffix}"
            return "重庆市"
        return _normalize_municipality_expression(normalized, municipality)
    return normalized


def _resolve_by_candidates(normalization: CnLocationNormalization, original_raw: str | None = None) -> LocationResolutionResult:
    raw = original_raw or normalization.normalized_query
    for query in normalization.candidate_queries:
        print(f"[WEATHER] geocoding try query={query}")
        try:
            results = _geocode_search(query)
        except Exception as exc:
            print(f"[WEATHER] geocoding failed error={exc}")
            continue

        best_result = None
        best_score = -999
        best_reason = "no_candidate"
        for result in results:
            score, reason = score_geocode_result(result, raw, normalization)
            if score > best_score:
                best_score = score
                best_result = result
                best_reason = reason

        if best_result is None:
            print(f"[WEATHER] geocoding candidate rejected score={best_score} reason=no_results")
            continue

        threshold = 9 if normalization.guessed_region_bias == "重庆" else 6
        display_name = _build_display_name(best_result)
        if best_score >= threshold:
            print(f"[WEATHER] geocoding candidate accepted score={best_score} name={display_name}")
            return LocationResolutionResult(
                ok=True,
                requested_location=raw,
                resolved_location=str(best_result.get("name") or raw),
                display_name=display_name,
                latitude=float(best_result["latitude"]),
                longitude=float(best_result["longitude"]),
            )
        print(f"[WEATHER] geocoding candidate rejected score={best_score} reason={best_reason}")

    return LocationResolutionResult(ok=False, requested_location=raw, reason="low_confidence_geocoding_result")


def _geocode_search(query: str) -> list[dict[str, Any]]:
    response = requests.get(
        "https://geocoding-api.open-meteo.com/v1/search",
        params={"name": query, "count": 8, "language": "zh", "format": "json"},
        timeout=WEATHER_API_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    payload = response.json()
    return payload.get("results", []) or []


def score_geocode_result(result: dict[str, Any], raw_input: str, normalized: CnLocationNormalization) -> tuple[int, str]:
    name = str(result.get("name", "")).strip()
    admin1 = str(result.get("admin1", "")).strip()
    admin2 = str(result.get("admin2", "")).strip()
    country = str(result.get("country", "")).strip()
    country_code = str(result.get("country_code", "")).strip().upper()
    combined = " ".join(piece for piece in (name, admin2, admin1, country) if piece)

    score = 0
    reasons: list[str] = []
    normalized_raw = _normalize_location_text(raw_input)

    if normalized.is_china_location and (country == "中国" or country.lower() == "china" or country_code == "CN"):
        score += 3
        reasons.append("china")
    elif normalized.is_china_location:
        score -= 4
        reasons.append("not_china")

    if normalized.guessed_region_bias == "重庆":
        if "重庆" in combined:
            score += 6
            reasons.append("chongqing_bias")
        else:
            score -= 6
            reasons.append("not_chongqing")

    if normalized_raw and normalized_raw in combined:
        score += 4
        reasons.append("contains_raw")

    if normalized.normalized_query and normalized.normalized_query in combined:
        score += 4
        reasons.append("contains_normalized")

    if normalized_raw == name:
        score += 3
        reasons.append("exact_name")

    district_term = _strip_municipality_prefix(normalized_raw)
    if district_term and district_term in combined:
        score += 2
        reasons.append("district_match")

    if any(token for token in (admin1, admin2)):
        score += 1
        reasons.append("admin_complete")

    if district_term in CHONGQING_PRIORITY_TERMS and "重庆" not in combined:
        score -= 5
        reasons.append("priority_term_not_chongqing")

    reason = ",".join(reasons) if reasons else "no_signal"
    return score, reason


def _extract_explicit_location(normalized: str) -> str | None:
    for suffix in EXPLICIT_LOCATION_SUFFIXES:
        if normalized == suffix:
            return None
        if normalized.endswith(suffix):
            location = _clean_location_text(normalized[: -len(suffix)])
            if location:
                return location

    explicit_patterns = (
        r"^(?:帮我查一下|查一下|帮我看一下|看看)(?P<location>[\u4e00-\u9fa5A-Za-z·\-]{1,30})(?:的)?天气.*$",
        r"^(?P<location>[\u4e00-\u9fa5A-Za-z·\-]{1,30})(?:今天|今日|现在)?天气.*$",
    )
    for pattern in explicit_patterns:
        match = re.match(pattern, normalized)
        if not match:
            continue
        location = _clean_location_text(match.group("location"))
        if location:
            return location
    return None


def _normalize_location_text(text: str) -> str:
    cleaned = str(text or "").strip()
    translation = str.maketrans({"（": "(", "）": ")", "，": ",", "。": ".", "：": ":", "　": " "})
    cleaned = cleaned.translate(translation)
    cleaned = re.sub(r"\s+", "", cleaned)
    cleaned = re.sub(r"(今天天气如何|今日天气|现在天气怎么样|现在天气如何|天气怎么样|天气如何|天气怎样|今天天气|现在天气|weather|天气|现在冷吗|冷吗|现在热吗|热吗)$", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(帮我查一下|查一下|帮我看一下|看看)", "", cleaned)
    cleaned = cleaned.strip(" ,.:;!?")
    return cleaned


def _clean_location_text(text: str) -> str:
    return _normalize_location_text(text).removesuffix("的").strip()


def _is_chinese_location(text: str) -> bool:
    if text in KNOWN_NON_CHINA_CJK_LOCATIONS:
        return False
    return bool(re.search(r"[\u4e00-\u9fff]", text))


def _strip_municipality_prefix(text: str) -> str:
    stripped = text
    for prefix in ("重庆市", "重庆", "北京市", "北京", "上海市", "上海", "天津市", "天津"):
        if stripped.startswith(prefix):
            stripped = stripped[len(prefix):]
            break
    return stripped.strip()


def _dedupe_direct_municipality(text: str) -> str:
    for city in DIRECT_MUNICIPALITIES:
        text = re.sub(rf"^(?:{city}市?)+", city, text)
    return text


def _detect_municipality_prefix(text: str) -> str | None:
    deduped = _dedupe_direct_municipality(text)
    for city in DIRECT_MUNICIPALITIES:
        if deduped == city or deduped.startswith(city):
            return city
    return None


def _normalize_chongqing_expression(text: str) -> str:
    district_piece = _strip_municipality_prefix(_dedupe_direct_municipality(text))
    if not district_piece:
        return "重庆市"
    if district_piece.endswith(("区", "县")):
        return f"重庆市{district_piece}"
    if district_piece in CHONGQING_PRIORITY_TERMS:
        return f"重庆市{district_piece}区"
    return f"重庆市{district_piece}"


def _normalize_municipality_expression(text: str, municipality: str) -> str:
    district_piece = _strip_municipality_prefix(_dedupe_direct_municipality(text))
    if not district_piece:
        return f"{municipality}市"
    if district_piece.endswith(("区", "县", "市")):
        return f"{municipality}市{district_piece}"
    if len(district_piece) <= 4:
        return f"{municipality}市{district_piece}区"
    return f"{municipality}市{district_piece}"


def _dedupe_keep_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _build_display_name(result: dict[str, Any]) -> str:
    name = str(result.get("name", "")).strip()
    admin1 = str(result.get("admin1", "")).strip()
    admin2 = str(result.get("admin2", "")).strip()
    country = str(result.get("country", "")).strip()
    pieces = [piece for piece in (name, admin2, admin1, country) if piece]
    deduped: list[str] = []
    for piece in pieces:
        if piece not in deduped:
            deduped.append(piece)
    return " / ".join(deduped) if deduped else name
