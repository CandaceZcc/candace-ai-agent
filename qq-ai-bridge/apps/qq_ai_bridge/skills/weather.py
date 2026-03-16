"""Weather query skill."""

from __future__ import annotations

from apps.qq_ai_bridge.adapters.napcat_client import send_private_msg
from apps.qq_ai_bridge.services.weather_service import (
    build_weather_reply,
    detect_weather_intent,
    is_weather_query,
    query_weather_by_intent,
)
from apps.qq_ai_bridge.skills.base import SkillContext, SkillResult


class WeatherSkill:
    """Handle local weather queries without OCAI."""

    name = "weather"

    def match_reason(self, context: SkillContext) -> str:
        if not context.is_private:
            return "not_private"
        return "weather_query" if is_weather_query(context.effective_text) else "not_weather_query"

    def can_handle(self, context: SkillContext) -> bool:
        return context.is_private and is_weather_query(context.effective_text)

    def handle(self, context: SkillContext) -> SkillResult:
        intent = detect_weather_intent(context.effective_text)
        if intent is None:
            return SkillResult(handled=False, source=self.name, status="ignore")
        result = query_weather_by_intent(intent)
        send_private_msg(context.user_id, build_weather_reply(result))
        return SkillResult(handled=True, source=self.name)
