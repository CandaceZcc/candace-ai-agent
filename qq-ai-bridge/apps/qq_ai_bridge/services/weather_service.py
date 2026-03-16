"""Weather query helpers."""

from __future__ import annotations

import re
import traceback

import requests

from apps.qq_ai_bridge.config.settings import DEFAULT_WEATHER_CITY, WEATHER_API_TIMEOUT_SECONDS


WEATHER_QUERY_PATTERNS = (
    r"今天天气如何",
    r"今日天气",
    r"天气如何",
    r"现在天气怎么样",
    r".+今天天气",
)

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


def is_weather_query(text: str) -> bool:
    normalized = str(text or "").strip()
    return any(re.search(pattern, normalized) for pattern in WEATHER_QUERY_PATTERNS)


def extract_weather_city(text: str) -> str:
    raw = str(text or "").strip()
    match = re.search(r"([\u4e00-\u9fa5A-Za-z]+)(今天|今日|现在)?天气", raw)
    if match:
        city = re.sub(r"(今天|今日|现在)$", "", match.group(1).strip()).strip()
        if city not in {"今天", "今日", "现在", "天气"}:
            return city
    return DEFAULT_WEATHER_CITY


def query_weather(city: str) -> dict:
    print(f"[WEATHER] query city={city}")
    try:
        geo_resp = requests.get(
            "https://geocoding-api.open-meteo.com/v1/search",
            params={"name": city, "count": 1, "language": "zh", "format": "json"},
            timeout=WEATHER_API_TIMEOUT_SECONDS,
        )
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()
        results = geo_data.get("results", [])
        if not results:
            raise ValueError("no_geocoding_result")

        result = results[0]
        latitude = result["latitude"]
        longitude = result["longitude"]
        resolved_name = result.get("name") or city

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
            "city": resolved_name,
            "temperature": temp,
            "apparent_temperature": apparent,
            "condition": condition,
        }
    except Exception as exc:
        print(f"[WEATHER] failed error={exc}")
        traceback.print_exc()
        return {"ok": False, "error": str(exc), "city": city}


def build_weather_reply(weather_result: dict) -> str:
    if not weather_result.get("ok"):
        return "暂时获取不到天气信息，请稍后再试。"

    city = weather_result["city"]
    temp = weather_result.get("temperature")
    apparent = weather_result.get("apparent_temperature")
    condition = weather_result.get("condition", "天气状况未知")
    if temp is None:
        return f"{city}当前天气信息不完整，请稍后再试。"

    comfort = "体感舒适，今晚出门问题不大。" if apparent is not None and 18 <= float(apparent) <= 28 else "注意根据体感温度调整穿着。"
    return f"{city}现在 {temp}°C，{condition}。\n{comfort}"
