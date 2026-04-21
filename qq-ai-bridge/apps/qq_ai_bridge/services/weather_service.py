import re
from dataclasses import dataclass

import requests

from apps.qq_ai_bridge.config.settings import DEFAULT_WEATHER_LOCATION, WEATHER_API_TIMEOUT_SECONDS


@dataclass
class LocationResolutionResult:
    """Represents the result of attempting to resolve a location string."""

    ok: bool
    requested_location: str
    reason: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    resolved_location: str | None = None
    display_name: str | None = None


@dataclass
class CnLocationNormalization:
    """Represents the normalized candidate queries for a Chinese location."""

    normalized_query: str
    candidate_queries: list[str]
    is_china_location: bool
    guessed_region_bias: str | None


def query_weather_for_coordinates(
    requested_location: str, lat: float, lon: float, display_name: str | None = None
) -> str:
    """
    Query the Open-Meteo API for weather at a specific latitude and longitude.

    Args:
        requested_location: The location string originally requested.
        lat: The latitude to query.
        lon: The longitude to query.
        display_name: An optional friendly display name for the location.

    Returns:
        A formatted string describing the weather conditions.
    """
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
            "&current=temperature_2m,relative_humidity_2m,apparent_temperature,precipitation,weather_code"
            "&timezone=Asia%2FShanghai"
        )
        resp = requests.get(url, timeout=WEATHER_API_TIMEOUT_SECONDS)
        resp.raise_for_status()
        data = resp.json()
        current = data.get("current", {})
        temp = current.get("temperature_2m", "未知")
        humidity = current.get("relative_humidity_2m", "未知")
        apparent = current.get("apparent_temperature", "未知")
        precip = current.get("precipitation", 0)

        loc_name = display_name or requested_location
        report = (
            f"📍 {loc_name}\n"
            f"🌡️ 气温 {temp}℃ (体感 {apparent}℃)\n"
            f"💧 湿度 {humidity}%\n"
            f"☔ 降水 {precip}mm"
        )
        return report
    except requests.RequestException as e:
        msg = f"获取天气数据失败（网络错误），请稍后再试。原因：{e}"
        return build_weather_error(msg, city=requested_location)
    except KeyError as e:
        msg = f"获取天气数据失败（格式解析错误），请稍后再试。原因：{e}"
        return build_weather_error(msg, city=requested_location)


def build_weather_error(base_msg: str, reason: str | None = None, city: str | None = None) -> str:
    """Build a standard weather error message."""
    parts = [base_msg]
    if city:
        parts.append(f"地名：{city}")
    if reason:
        parts.append(f"原因：{reason}")
    return " | ".join(parts)


def detect_weather_intent(text: str) -> str | None:
    """Detect if the user is asking about the weather."""
    cleaned = re.sub(r"\[CQ:at,qq=\d+\]", "", text).strip()
    if not cleaned:
        return None
    weather_pattern = r"(.*?)(的天气|天气|现在冷吗|冷吗|现在热吗|热吗)$"
    match = re.search(weather_pattern, cleaned, re.IGNORECASE)
    if match:
        city = match.group(1).strip()
        return city
    return None


def handle_weather_query(user_text: str) -> str | None:
    """
    Main entrypoint for handling a weather request based on user text.

    Args:
        user_text: The user's input text.

    Returns:
        The weather report string, or None if the intent was not detected.
    """
    raw_location = detect_weather_intent(user_text)
    if raw_location is None:
        return None

    raw_location = raw_location.strip()
    if not raw_location:
        raw_location = DEFAULT_WEATHER_LOCATION

    print(f"[WEATHER] Resolving location for: {raw_location}")

    if "Zhuhai" in raw_location or "珠海" in raw_location:
        return query_weather_for_coordinates(
            raw_location, 22.27, 113.56, display_name="广东珠海"
        )
    elif "北京" in raw_location:
        return query_weather_for_coordinates(
            raw_location, 39.90, 116.40, display_name="北京"
        )

    return build_weather_error(
        f"抱歉，我目前只能查几个固定城市的天气，无法识别：{raw_location}"
    )


def is_weather_query(text: str) -> bool:
    """Return whether the text looks like a weather query."""
    return detect_weather_intent(text) is not None


def query_weather_by_intent(intent: str) -> str:
    """Compatibility wrapper used by WeatherSkill."""
    query_text = (intent or "").strip()
    if not query_text:
        query_text = DEFAULT_WEATHER_LOCATION
    if not query_text.endswith("天气"):
        query_text = f"{query_text}天气"
    return handle_weather_query(query_text) or build_weather_error("天气查询失败。", city=intent)


def build_weather_reply(result: str) -> str:
    """Compatibility wrapper used by WeatherSkill."""
    return str(result or "暂时没有获取到天气信息。").strip()
