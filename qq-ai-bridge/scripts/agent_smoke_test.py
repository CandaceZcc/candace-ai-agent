"""Smoke-test the owner-private Agents SDK runtime without sending QQ messages."""

from __future__ import annotations

import argparse
import asyncio
import json
import time

from apps.qq_ai_bridge.config.settings import agent_config_summary
from apps.qq_ai_bridge.services.agent_route_service import classify_agent_route
from shared.ai.agent_runtime import AgentRunRequest, AgentRuntime


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config-only", action="store_true", help="Print redacted config only")
    parser.add_argument("--text", help="Run a text-only private-chat smoke test")
    parser.add_argument("--web-search", help="Run a hosted web-search smoke test")
    parser.add_argument(
        "--accept-billable-probe",
        action="store_true",
        help="Required for hosted web-search smoke tests that may bill the provider",
    )
    args = parser.parse_args(argv)

    if args.config_only:
        print(json.dumps(agent_config_summary(), ensure_ascii=False, sort_keys=True))
        return 0
    if args.web_search and not args.accept_billable_probe:
        print(json.dumps({"ok": False, "error": "requires --accept-billable-probe"}))
        return 2

    text = args.web_search or args.text
    if not text:
        parser.error("one of --config-only, --text, or --web-search is required")

    decision = classify_agent_route(text)
    if args.web_search:
        decision = decision.__class__("current_events", ("web_search",))
    request = AgentRunRequest(
        route=decision.route,
        user_text=text,
        compact_context="",
        allowed_tool_names=decision.allowed_tool_names,
        trace_id="agent-smoke-test",
    )
    started_at = time.monotonic()
    result = asyncio.run(AgentRuntime().run(request))
    payload = {
        "ok": result.ok,
        "provider": result.provider,
        "model": result.model,
        "tools": list(result.tool_names),
        "latency_ms": int((time.monotonic() - started_at) * 1000),
        "input_tokens": _result_int(result, "input_tokens"),
        "cached_input_tokens": _result_int(result, "cached_input_tokens"),
        "output_tokens": _result_int(result, "output_tokens"),
        "hosted_search_calls": _result_int(result, "hosted_search_calls"),
        "local_tool_calls": _result_int(result, "local_tool_calls"),
        "failure_code": result.failure_code,
        "used_legacy_fallback": result.used_legacy_fallback,
        "output_preview": result.output_text[:120],
    }
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    return 0 if result.ok else 1


def _result_int(result, name: str) -> int:
    return max(0, int(getattr(result, name, 0) or 0))


if __name__ == "__main__":
    raise SystemExit(main())
