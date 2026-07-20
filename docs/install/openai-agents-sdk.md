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

## API Key Plan

Use separate keys for separate jobs. Do not reuse a hosted-tool/agent key for
ordinary chat or image generation unless the provider account is meant to pay for
that traffic.

- Ordinary chat: keep the existing `KIMI_API_KEY`, `KIMI_BASE_URL`, and
  `KIMI_MODEL` path for DeepSeek v4 chat. This remains the legacy fallback when
  `AGENT_RUNTIME_ENABLED=false` or a safe owner-private agent turn falls back.
- Image generation: use `DRAW_API_KEY`, `DRAW_BASE_URL`, and `DRAW_MODEL` for
  the banana image provider. `/draw` is not routed through the Agents SDK.
- Owner-private agent control: use the quota API 5.6 key only for
  `AGENT_PROVIDER=responses_proxy` or `AGENT_PROVIDER=chat_compatible`.
  Prefer `responses_proxy` when the gateway supports `/v1/responses`, because
  hosted web search and computer probes can only be trusted after Responses
  response items prove them. Use `chat_compatible` only for text plus local
  function tools.

Before enabling the runtime, record the quota API base URL, model name, endpoint
type, and whether each billable probe was accepted. Keep
`OPENAI_HOSTED_WEB_SEARCH_ENABLED=false` and `OPENAI_COMPUTER_USE_ENABLED=false`
until the exact endpoint/model passes the matching probe.

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
