"""Provider bindings for the owner-private Agents SDK runtime."""

from dataclasses import dataclass
from typing import Literal

from agents import (
    AsyncOpenAI,
    OpenAIChatCompletionsModel,
    OpenAIResponsesModel,
    set_tracing_disabled,
)

from apps.qq_ai_bridge.config.settings import (
    AGENT_PROVIDER,
    AGENT_TRACE_EXPORT_ENABLED,
    CHAT_COMPATIBLE_API_KEY,
    CHAT_COMPATIBLE_BASE_URL,
    CHAT_COMPATIBLE_MODEL,
    OPENAI_AGENT_MODEL,
    OPENAI_API_KEY,
    OPENAI_COMPUTER_USE_ENABLED,
    OPENAI_HOSTED_WEB_SEARCH_ENABLED,
    RESPONSES_PROXY_API_KEY,
    RESPONSES_PROXY_BASE_URL,
    RESPONSES_PROXY_MODEL,
)

ProviderName = Literal["openai", "responses_proxy", "chat_compatible"]


@dataclass(frozen=True)
class ProviderCapabilities:
    responses: bool
    function_tools: bool
    hosted_web_search: bool
    builtin_computer: bool
    openai_trace_export: bool
    verified: bool


@dataclass(frozen=True)
class AgentModelBinding:
    provider: ProviderName
    model: object
    model_name: str
    capabilities: ProviderCapabilities


def build_agent_model_binding(provider: ProviderName | None = None) -> AgentModelBinding:
    """Build an Agents SDK model binding for the configured provider."""
    selected_provider = provider or AGENT_PROVIDER
    if selected_provider == "openai":
        return _build_openai_binding()
    if selected_provider == "responses_proxy":
        return _build_responses_proxy_binding()
    if selected_provider == "chat_compatible":
        return _build_chat_compatible_binding()
    raise ValueError(f"unsupported agent provider: {selected_provider}")


def _build_openai_binding() -> AgentModelBinding:
    set_tracing_disabled(not AGENT_TRACE_EXPORT_ENABLED)
    client = AsyncOpenAI(api_key=OPENAI_API_KEY)
    model = OpenAIResponsesModel(model=OPENAI_AGENT_MODEL, openai_client=client)
    capabilities = ProviderCapabilities(
        responses=True,
        function_tools=True,
        hosted_web_search=OPENAI_HOSTED_WEB_SEARCH_ENABLED,
        builtin_computer=OPENAI_COMPUTER_USE_ENABLED,
        openai_trace_export=AGENT_TRACE_EXPORT_ENABLED,
        verified=True,
    )
    return AgentModelBinding(
        provider="openai",
        model=model,
        model_name=OPENAI_AGENT_MODEL,
        capabilities=capabilities,
    )


def _build_responses_proxy_binding() -> AgentModelBinding:
    set_tracing_disabled(True)
    client = AsyncOpenAI(
        api_key=RESPONSES_PROXY_API_KEY,
        base_url=RESPONSES_PROXY_BASE_URL,
    )
    model = OpenAIResponsesModel(model=RESPONSES_PROXY_MODEL, openai_client=client)
    capabilities = ProviderCapabilities(
        responses=True,
        function_tools=True,
        hosted_web_search=False,
        builtin_computer=False,
        openai_trace_export=False,
        verified=False,
    )
    return AgentModelBinding(
        provider="responses_proxy",
        model=model,
        model_name=RESPONSES_PROXY_MODEL,
        capabilities=capabilities,
    )


def _build_chat_compatible_binding() -> AgentModelBinding:
    set_tracing_disabled(True)
    client = AsyncOpenAI(
        api_key=CHAT_COMPATIBLE_API_KEY,
        base_url=CHAT_COMPATIBLE_BASE_URL,
    )
    model = OpenAIChatCompletionsModel(model=CHAT_COMPATIBLE_MODEL, openai_client=client)
    capabilities = ProviderCapabilities(
        responses=False,
        function_tools=True,
        hosted_web_search=False,
        builtin_computer=False,
        openai_trace_export=False,
        verified=True,
    )
    return AgentModelBinding(
        provider="chat_compatible",
        model=model,
        model_name=CHAT_COMPATIBLE_MODEL,
        capabilities=capabilities,
    )


__all__ = [
    "AgentModelBinding",
    "ProviderCapabilities",
    "ProviderName",
    "build_agent_model_binding",
]
