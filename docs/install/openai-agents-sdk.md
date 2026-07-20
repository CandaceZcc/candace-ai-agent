# OpenAI Agents SDK Canary

Phase A adds an owner-private QQ canary for the OpenAI Agents SDK. QQ remains the
only terminal; NapCat and the local PC Agent stay in place.

## Billing and Credentials

ChatGPT Plus is separate from Platform/API billing and cannot authenticate these
scripts. Put API keys only in `~/.candace/qq-ai-bridge.env` or another ignored
machine-local file, then restrict it:

```bash
chmod 600 ~/.candace/qq-ai-bridge.env
```

Supported provider modes:

- `openai`: official OpenAI Responses API.
- `responses_proxy`: third-party `/v1/responses` proxy after probes pass.
- `chat_compatible`: OpenAI-compatible `/v1/chat/completions`, local function
  tools only.

## Capability Probes

Keep hosted tools off until the exact endpoint/model passes:

```bash
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/probe_agent_provider.py --provider responses_proxy --text
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/probe_agent_provider.py --provider responses_proxy --web-search --accept-billable-probe
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/probe_agent_provider.py --provider responses_proxy --computer --accept-billable-probe
```

Exit codes are `0` supported, `2` unsupported/disabled, and `1` config or
network failure. Third-party gateway billing and data handling are controlled by
that gateway.

## Smoke Tests

```bash
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/agent_smoke_test.py --config-only
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/agent_smoke_test.py --text "只回复 OK"
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/agent_smoke_test.py --web-search "OpenAI 当前 API 文档首页标题" --accept-billable-probe
```

Output is redacted JSON with provider, model, tools, latency, and failure code.
Usage fields may be zero when the provider does not report token details; zero
does not mean free.

## Canary Sequence

1. Config-only check passes with `AGENT_RUNTIME_ENABLED=false`.
2. Minimal text smoke test passes from the remote host.
3. Enable `AGENT_RUNTIME_ENABLED=true` for owner-private QQ only.
4. Send five ordinary private messages and confirm no tools are exposed.
5. Send one current-events request and confirm `web_search_call` plus visible URLs.
6. Stop PC Agent and confirm browser requests fail safely.
7. Restore PC Agent and execute a read-only browser inspection.
8. Trigger an approval-required action and confirm no action executes.
9. Disable `AGENT_RUNTIME_ENABLED` and confirm legacy private chat works.
10. Review redacted metrics and provider billing before continuing.

## PC Agent Boundary

The SDK receives only allowlisted local function tools. It never receives raw
shell, arbitrary executable, arbitrary local file path, arbitrary HTTP request,
environment variables, or secret headers. High-impact actions return
`needs_approval=true` without execution.

## Rollback

Set:

```dotenv
AGENT_RUNTIME_ENABLED=false
OPENAI_HOSTED_WEB_SEARCH_ENABLED=false
OPENAI_COMPUTER_USE_ENABLED=false
```

Restart with the repository launcher. Group QQ behavior remains on the existing
path throughout Phase A.
