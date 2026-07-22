# OpenAI Agents SDK Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the owner-private OpenClaw chat path with a bounded OpenAI Agents SDK runtime that can use hosted web search when the configured API surface supports it and can drive the existing PC Agent through local tools.

**Architecture:** Keep NapCat, the ordered QQ skill router, private queue, scheduler, and PC Agent. Add an in-process agent runtime with three explicit provider modes: official OpenAI Responses, a third-party Responses proxy, and Chat Completions compatibility. Detect capabilities before constructing a run, expose only route-relevant tools, and retain the current `llm_client` as a feature-flagged rollback path.

**Tech Stack:** Python 3.10+, OpenAI Agents SDK (`openai-agents`), OpenAI Responses API, existing Flask/Waitress QQ bridge, existing PC Agent HTTP service, `unittest`, `unittest.mock`

---

## Prerequisites and decisions

- Work from a clean branch based on the latest `main`.
- Do not deploy or edit the remote service until all local tests in this plan pass.
- Do not put a real API key in the repository.
- A third-party endpoint serving OpenAI 5.5/5.6 models is not assumed to support hosted tools. The decisive contract is its API surface:
  - `openai`: official `api.openai.com` Responses API;
  - `responses_proxy`: third-party `/v1/responses` proxy, enabled only after capability probes pass;
  - `chat_compatible`: `/v1/chat/completions`, local function tools only.
- Start with `OPENAI_HOSTED_WEB_SEARCH_ENABLED=false` and `OPENAI_COMPUTER_USE_ENABLED=false`. Enable one capability at a time after the owner-private canary is stable.
- Agents SDK runs are stateless across QQ turns in this phase. The bridge remains the owner of compact history.

## Task 1: Pin the SDK and validate configuration

**Files:**

- Modify: `requirements.txt`
- Modify: `qq-ai-bridge/.env.example`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/config/settings.py`
- Create: `qq-ai-bridge/tests/test_agent_config.py`

- [ ] **Step 1: Write failing configuration tests**

Create `qq-ai-bridge/tests/test_agent_config.py` with isolated environment parsing tests. Follow the existing `test_kimi_config_defaults.py` reload pattern so each case controls `os.environ` without leaking values.

Cover these contracts:

```python
class AgentConfigTests(unittest.TestCase):
    def test_runtime_is_disabled_by_default(self): ...
    def test_provider_defaults_to_openai(self): ...
    def test_responses_proxy_requires_base_url_key_and_model(self): ...
    def test_chat_compatible_rejects_hosted_web_search(self): ...
    def test_chat_compatible_rejects_builtin_computer_use(self): ...
    def test_limits_reject_zero_or_negative_values(self): ...
    def test_secret_values_are_not_returned_by_config_summary(self): ...
```

Expected provider values are exactly `openai`, `responses_proxy`, and `chat_compatible`. An invalid provider disables only the new runtime and emits a safe configuration warning.

- [ ] **Step 2: Run the focused test and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_agent_config.py -v
```

Expected: failure because the new settings and validation helpers do not exist.

- [ ] **Step 3: Add the dependency**

Append the latest stable version verified from the Python Package Index on 2026-07-20:

```text
openai-agents==0.18.3
```

Re-check the package index immediately before implementation. If a newer stable release exists, review its changelog and update this pin deliberately; do not use an unbounded range.

- [ ] **Step 4: Add safe examples to `qq-ai-bridge/.env.example`**

Add this block with empty secrets:

```dotenv
# OpenAI Agents SDK (owner-private canary)
AGENT_RUNTIME_ENABLED=false
AGENT_PROVIDER=openai
OPENAI_API_KEY=
OPENAI_AGENT_MODEL=gpt-5.6
OPENAI_HOSTED_WEB_SEARCH_ENABLED=false
OPENAI_COMPUTER_USE_ENABLED=false

# Third-party Responses proxy; use only after capability probes pass
RESPONSES_PROXY_API_KEY=
RESPONSES_PROXY_BASE_URL=
RESPONSES_PROXY_MODEL=

# OpenAI-compatible Chat Completions; local function tools only
CHAT_COMPATIBLE_API_KEY=
CHAT_COMPATIBLE_BASE_URL=
CHAT_COMPATIBLE_MODEL=

AGENT_PROVIDER_CAPABILITY_STRICT=true
AGENT_MAX_TURNS=6
AGENT_MAX_TOOL_CALLS=8
AGENT_RUN_TIMEOUT_SECONDS=90
AGENT_TRACE_EXPORT_ENABLED=false
AGENT_FALLBACK_TO_LEGACY=true
```

- [ ] **Step 5: Implement parsed settings and a redacted diagnostic summary**

In `settings.py`, reuse local boolean/integer parsing helpers if present. Export immutable primitive values plus:

```python
AGENT_PROVIDER_VALUES = {"openai", "responses_proxy", "chat_compatible"}


def validate_agent_settings() -> list[str]:
    """Return safe validation errors; never include credential values."""


def agent_config_summary() -> dict[str, object]:
    """Return provider, models, flags, and secret set/missing states only."""
```

Validation rules:

- runtime enabled + `openai` requires `OPENAI_API_KEY`;
- runtime enabled + `responses_proxy` requires proxy base URL, key, and model;
- runtime enabled + `chat_compatible` requires chat-compatible base URL, key, and model;
- `chat_compatible` plus either hosted capability is an error;
- URL values must use `https`, except loopback URLs in tests/development;
- max turns, max tool calls, and timeout are positive and capped at `12`, `20`, and `300` respectively;
- tracing export defaults off.

- [ ] **Step 6: Run the focused test**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_agent_config.py -v
```

Expected: all configuration tests pass.

- [ ] **Step 7: Commit**

```bash
git add requirements.txt qq-ai-bridge/.env.example qq-ai-bridge/apps/qq_ai_bridge/config/settings.py qq-ai-bridge/tests/test_agent_config.py
git commit -m "feat: add agents sdk configuration"
```

## Task 2: Build the provider factory and capability matrix

**Files:**

- Create: `qq-ai-bridge/shared/ai/agent_provider.py`
- Create: `qq-ai-bridge/tests/test_agent_provider.py`

- [ ] **Step 1: Write provider contract tests**

The tests must not call a network. Patch `AsyncOpenAI`, `OpenAIResponsesModel`, and `OpenAIChatCompletionsModel` and assert construction arguments.

Required cases:

```python
class AgentProviderTests(unittest.TestCase):
    def test_official_openai_uses_responses_model(self): ...
    def test_responses_proxy_uses_custom_client_and_responses_model(self): ...
    def test_chat_compatible_uses_chat_completions_model(self): ...
    def test_chat_provider_never_reports_hosted_web_search(self): ...
    def test_proxy_capabilities_start_unverified(self): ...
    def test_official_provider_does_not_override_base_url(self): ...
```

- [ ] **Step 2: Run the test and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_agent_provider.py -v
```

Expected: import failure for `shared.ai.agent_provider`.

- [ ] **Step 3: Implement small provider value objects**

Create:

```python
from dataclasses import dataclass
from typing import Literal

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
```

Factory behavior:

- official OpenAI: `OpenAIResponsesModel` or default OpenAI provider, with hosted capabilities allowed by configuration;
- Responses proxy: `AsyncOpenAI(api_key=..., base_url=...)` plus `OpenAIResponsesModel`; capabilities remain false until a probe result is injected;
- Chat-compatible: `AsyncOpenAI` plus `OpenAIChatCompletionsModel`; hosted capabilities always false;
- provider creation never logs or returns API keys.

- [ ] **Step 4: Disable OpenAI trace export for non-official providers**

When the configured provider is `responses_proxy` or `chat_compatible`, call `set_tracing_disabled(True)` unless a separate official trace-export key is explicitly introduced in a later change. Do not send email or QQ content to OpenAI tracing by accident.

- [ ] **Step 5: Run the focused tests**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_agent_provider.py -v
```

Expected: all provider factory tests pass.

- [ ] **Step 6: Commit**

```bash
git add qq-ai-bridge/shared/ai/agent_provider.py qq-ai-bridge/tests/test_agent_provider.py
git commit -m "feat: add agent provider capability matrix"
```

## Task 3: Add an explicit capability probe command

**Files:**

- Create: `qq-ai-bridge/shared/ai/capability_probe.py`
- Create: `qq-ai-bridge/scripts/probe_agent_provider.py`
- Create: `qq-ai-bridge/tests/test_capability_probe.py`
- Modify: `docs/install/run.md`

- [ ] **Step 1: Write tests for probe interpretation**

Probe parsing must be independent of live networking. Feed synthetic success/error responses and cover:

```python
class CapabilityProbeTests(unittest.TestCase):
    def test_chat_compatible_skips_hosted_probes(self): ...
    def test_responses_text_success_marks_responses_only(self): ...
    def test_web_search_call_item_marks_search_supported(self): ...
    def test_model_text_without_web_search_call_does_not_pass_search_probe(self): ...
    def test_computer_call_item_marks_computer_supported(self): ...
    def test_401_and_403_are_redacted(self): ...
    def test_unknown_error_does_not_leak_response_body(self): ...
```

- [ ] **Step 2: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_capability_probe.py -v
```

- [ ] **Step 3: Implement non-destructive probes**

The script supports:

```bash
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/probe_agent_provider.py --provider responses_proxy --text
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/probe_agent_provider.py --provider responses_proxy --web-search
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/probe_agent_provider.py --provider responses_proxy --computer
```

Rules:

- `--text` sends a minimal Responses request and checks response-item parsing;
- `--web-search` asks a deterministic current fact and passes only if a real `web_search_call` item and cited output are returned;
- `--computer` requests a screenshot action but never executes the returned action; pass only if a well-formed `computer_call` is returned;
- print an estimated-cost warning and require `--accept-billable-probe` for the two hosted-tool probes;
- never print credentials, authorization headers, or a full upstream error body;
- return exit code `0` for supported, `2` for unsupported, and `1` for configuration/network failure.

This probe demonstrates gateway support; it does not prove that every model/tool combination will continue to work. Store no global capability cache. Production configuration remains explicit.

- [ ] **Step 4: Document proxy verification**

In `docs/install/run.md`, add a section explaining:

- an underlying GPT-5.5/5.6 model does not guarantee hosted tool forwarding;
- test `/v1/responses` before enabling `responses_proxy`;
- enable web search and computer flags only after their exact probes pass;
- third-party gateway billing and data handling are controlled by that gateway;
- ChatGPT Plus cannot authenticate the script.

- [ ] **Step 5: Run tests and inspect CLI help without credentials**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_capability_probe.py -v
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/probe_agent_provider.py --help
```

Expected: tests pass; help exits `0` without importing configuration that requires a secret.

- [ ] **Step 6: Commit**

```bash
git add qq-ai-bridge/shared/ai/capability_probe.py qq-ai-bridge/scripts/probe_agent_provider.py qq-ai-bridge/tests/test_capability_probe.py docs/install/run.md
git commit -m "feat: add agent provider capability probe"
```

## Task 4: Implement bounded agent execution and redacted telemetry

**Files:**

- Create: `qq-ai-bridge/shared/ai/agent_runtime.py`
- Create: `qq-ai-bridge/shared/ai/agent_telemetry.py`
- Create: `qq-ai-bridge/tests/test_agent_runtime.py`
- Create: `qq-ai-bridge/tests/test_agent_telemetry.py`

- [ ] **Step 1: Write failing runtime tests**

Mock `Runner.run` and a clock. Cover:

```python
class AgentRuntimeTests(unittest.IsolatedAsyncioTestCase):
    async def test_passes_max_turns_to_runner(self): ...
    async def test_times_out_at_configured_deadline(self): ...
    async def test_rejects_too_many_requested_tools_before_run(self): ...
    async def test_returns_typed_success(self): ...
    async def test_returns_typed_provider_failure(self): ...
    async def test_does_not_persist_an_sdk_session(self): ...
    async def test_fallback_is_attempted_at_most_once(self): ...
```

Telemetry tests must assert that strings resembling API keys, IMAP passwords, authorization headers, and email body samples are redacted.

- [ ] **Step 2: Run both tests and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_agent_runtime.py qq-ai-bridge/tests/test_agent_telemetry.py -v
```

- [ ] **Step 3: Implement typed run inputs and results**

Use contracts equivalent to:

```python
@dataclass(frozen=True)
class AgentRunRequest:
    route: str
    user_text: str
    compact_context: str
    allowed_tool_names: tuple[str, ...]
    trace_id: str | None


@dataclass(frozen=True)
class AgentRunResult:
    ok: bool
    output_text: str
    provider: str
    model: str
    tool_names: tuple[str, ...]
    failure_code: str | None = None
    used_legacy_fallback: bool = False
```

`AgentRuntime.run(request)` must:

1. validate settings and capability/tool compatibility;
2. resolve exactly the named tools through the tool registry;
3. create a short-lived `Agent` with provider binding and concise route instructions;
4. call `Runner.run(..., max_turns=AGENT_MAX_TURNS)` inside `asyncio.timeout`;
5. limit tool calls through SDK configuration if supported by the pinned version, otherwise enforce the count in hooks and stop the run;
6. normalize the final output through the existing reply sanitizer;
7. write redacted metrics;
8. optionally invoke the legacy LLM client once only when the failure is safe to retry and no non-idempotent local action ran.

Do not attach `SQLiteSession`, `OpenAIConversationsSession`, or another cross-turn SDK session.

- [ ] **Step 4: Implement redacted telemetry**

Record operational fields only:

```python
{
    "route": "private_chat",
    "provider": "responses_proxy",
    "model": "configured-model-name",
    "tools": ["web_search"],
    "latency_ms": 1234,
    "input_tokens": 0,
    "cached_input_tokens": 0,
    "output_tokens": 0,
    "hosted_search_calls": 1,
    "local_tool_calls": 0,
    "status": "ok",
    "failure_code": None,
}
```

Zero means the provider did not report usage; it does not mean the call was free. Do not estimate or persist raw request text in this module.

- [ ] **Step 5: Run focused tests**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_agent_runtime.py qq-ai-bridge/tests/test_agent_telemetry.py -v
```

- [ ] **Step 6: Commit**

```bash
git add qq-ai-bridge/shared/ai/agent_runtime.py qq-ai-bridge/shared/ai/agent_telemetry.py qq-ai-bridge/tests/test_agent_runtime.py qq-ai-bridge/tests/test_agent_telemetry.py
git commit -m "feat: add bounded agents sdk runtime"
```

## Task 5: Add route-specific tool selection and hosted web search

**Files:**

- Create: `qq-ai-bridge/shared/ai/agent_tools.py`
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/agent_route_service.py`
- Create: `qq-ai-bridge/tests/test_agent_tools.py`
- Create: `qq-ai-bridge/tests/test_agent_route_service.py`

- [ ] **Step 1: Write deterministic routing tests**

The router does not call an LLM. Cover Chinese and English examples:

```python
class AgentRouteServiceTests(unittest.TestCase):
    def test_normal_chat_exposes_no_tools(self): ...
    def test_current_news_exposes_web_search_only(self): ...
    def test_explicit_browser_request_exposes_pc_browser_tools_only(self): ...
    def test_email_command_is_not_routed_to_general_agent(self): ...
    def test_ambiguous_message_does_not_receive_computer_tools(self): ...
```

Use conservative trigger phrases. A false negative can return a capability/help message; a false positive could spend money or execute a computer action.

- [ ] **Step 2: Write capability filtering tests**

```python
class AgentToolsTests(unittest.TestCase):
    def test_web_search_constructed_only_when_enabled_and_supported(self): ...
    def test_proxy_without_verified_search_fails_closed(self): ...
    def test_chat_compatible_cannot_construct_web_search(self): ...
    def test_unknown_tool_name_is_rejected(self): ...
    def test_registry_returns_only_requested_tools(self): ...
```

- [ ] **Step 3: Run and confirm failures**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_agent_tools.py qq-ai-bridge/tests/test_agent_route_service.py -v
```

- [ ] **Step 4: Implement the registry**

Expose a strict name-to-factory mapping. The web entry returns SDK `WebSearchTool(search_context_size="low")` for the first canary. Do not instantiate or send the tool when the route does not request it.

The registry returns a typed `CapabilityUnavailable` error for:

- disabled feature flag;
- provider capability not verified;
- Chat Completions provider;
- daily budget guard denied;
- unsupported tool in the pinned SDK/model.

- [ ] **Step 5: Preserve citations in output**

Add a pure formatter that converts response URL annotations to QQ text:

```text
<answer text>

来源：
[1] <title> — https://example.com/page
```

Deduplicate identical URLs, cap the number of displayed sources, keep `https://` links intact, and use the existing reply splitting path if needed. Test this formatter with synthetic SDK response items.

- [ ] **Step 6: Run focused tests**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_agent_tools.py qq-ai-bridge/tests/test_agent_route_service.py -v
```

- [ ] **Step 7: Commit**

```bash
git add qq-ai-bridge/shared/ai/agent_tools.py qq-ai-bridge/apps/qq_ai_bridge/services/agent_route_service.py qq-ai-bridge/tests/test_agent_tools.py qq-ai-bridge/tests/test_agent_route_service.py
git commit -m "feat: add selective hosted web search"
```

## Task 6: Wrap existing PC Agent operations as local function tools

**Files:**

- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/browser_agent_service.py`
- Create: `qq-ai-bridge/shared/ai/pc_agent_tools.py`
- Create: `qq-ai-bridge/tests/test_pc_agent_tools.py`
- Modify: `qq-ai-bridge/shared/ai/agent_tools.py`

- [ ] **Step 1: Inventory existing PC Agent HTTP actions**

Read `browser_agent_service.py`, `skills/browser_agent.py`, `skills/desktop_agent.py`, and the PC Agent route handlers. List only existing non-destructive operations that have clear request and response schemas. Do not add new PC Agent capabilities in this task.

- [ ] **Step 2: Write failing function-tool tests**

Patch HTTP calls. Cover:

```python
class PcAgentToolsTests(unittest.IsolatedAsyncioTestCase):
    async def test_status_returns_small_structured_result(self): ...
    async def test_screenshot_redacts_local_path_from_model_output(self): ...
    async def test_open_url_rejects_non_http_schemes(self): ...
    async def test_action_times_out(self): ...
    async def test_unavailable_service_returns_typed_error(self): ...
    async def test_high_impact_action_requires_approval(self): ...
    async def test_tool_never_forwards_environment_or_secret_headers(self): ...
```

- [ ] **Step 3: Run and confirm failures**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_pc_agent_tools.py -v
```

- [ ] **Step 4: Extract typed service operations**

If `browser_agent_service.py` currently mixes natural-language prompting with HTTP calls, extract only its existing HTTP operations into small functions. Preserve the existing skill behavior and tests.

Return objects with bounded fields such as:

```python
@dataclass(frozen=True)
class PcActionResult:
    ok: bool
    action: str
    message: str
    needs_approval: bool = False
    approval_reason: str | None = None
```

- [ ] **Step 5: Create SDK function tools**

Wrap approved functions with `@function_tool` and concise docstrings. The initial registry should include no more than:

- `pc_agent_status`;
- `pc_open_http_url`;
- `pc_capture_screen`;
- existing safe browser inspect/click/type operations that pass the inventory review.

Never expose a raw shell, arbitrary executable, arbitrary local file path, or arbitrary HTTP request tool.

- [ ] **Step 6: Add approval boundaries**

The function tool must return `needs_approval=true` without execution for login changes, purchases, sends/submits, file uploads/downloads, deletion, security warning bypass, or any action not in the allowlist. Scheduled jobs cannot approve computer actions.

- [ ] **Step 7: Run focused and existing browser tests**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_pc_agent_tools.py qq-ai-bridge/tests/test_browser_agent_service.py qq-ai-bridge/tests/test_browser_agent_skill.py -v
```

- [ ] **Step 8: Commit**

```bash
git add qq-ai-bridge/apps/qq_ai_bridge/services/browser_agent_service.py qq-ai-bridge/shared/ai/pc_agent_tools.py qq-ai-bridge/shared/ai/agent_tools.py qq-ai-bridge/tests/test_pc_agent_tools.py
git commit -m "feat: expose bounded pc agent tools"
```

## Task 7: Integrate the runtime into owner-private chat behind a feature flag

**Files:**

- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/private_chat_service.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/agent_service.py`
- Modify: `qq-ai-bridge/tests/test_private_chat_service.py`
- Create: `qq-ai-bridge/tests/test_private_agent_integration.py`

- [ ] **Step 1: Trace the current private queue call path**

Before editing, identify the exact point after compact-context construction and before the current `call_ai`/CLI invocation. Keep queue admission, coalescing, emoji behavior, output normalization, and NapCat send behavior unchanged.

- [ ] **Step 2: Write integration tests**

Patch `AgentRuntime` and the legacy client. Cover:

```python
class PrivateAgentIntegrationTests(unittest.TestCase):
    def test_disabled_flag_uses_legacy_path(self): ...
    def test_enabled_owner_private_message_uses_agent_runtime(self): ...
    def test_group_service_is_unchanged(self): ...
    def test_compact_context_is_bounded_before_sdk_run(self): ...
    def test_capability_error_is_sent_without_legacy_retry(self): ...
    def test_safe_provider_failure_uses_legacy_once_when_enabled(self): ...
    def test_non_idempotent_tool_failure_never_falls_back(self): ...
```

- [ ] **Step 3: Run and confirm failures**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_private_agent_integration.py -v
```

- [ ] **Step 4: Add the feature-flagged branch**

Only owner-private messages use the new runtime in Phase A0. Even if the bridge permits other private users, gate the canary by `OWNER_QQ`. Group services stay on their current path.

Use `asyncio.run_coroutine_threadsafe` or the repository's existing async bridge pattern; do not call `asyncio.run` from an already-running event loop. Keep the current bounded executor and queue timeout behavior.

- [ ] **Step 5: Use deterministic route selection**

Before constructing the agent:

- classify normal, current-events, and PC Agent requests;
- reject explicit email commands here so the later `EmailSkill` owns them;
- pass only compact history and allowed tool names;
- preserve existing reply normalization and QQ sending.

- [ ] **Step 6: Run integration and regression tests**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_private_agent_integration.py \
  qq-ai-bridge/tests/test_private_chat_service.py \
  qq-ai-bridge/tests/test_chat_skill.py \
  qq-ai-bridge/tests/test_llm_client.py -v
```

- [ ] **Step 7: Commit**

```bash
git add qq-ai-bridge/apps/qq_ai_bridge/services/private_chat_service.py qq-ai-bridge/apps/qq_ai_bridge/services/agent_service.py qq-ai-bridge/tests/test_private_chat_service.py qq-ai-bridge/tests/test_private_agent_integration.py
git commit -m "feat: canary agents sdk in private qq chat"
```

## Task 8: Add runbook, cost controls, and Phase A0 verification

**Files:**

- Create: `docs/install/openai-agents-sdk.md`
- Modify: `docs/install/run.md`
- Modify: `README.md`
- Create: `qq-ai-bridge/scripts/agent_smoke_test.py`
- Create: `qq-ai-bridge/tests/test_agent_smoke_test.py`

- [ ] **Step 1: Write a smoke-test contract**

The script supports dry-run validation without sending QQ messages:

```bash
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/agent_smoke_test.py --config-only
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/agent_smoke_test.py --text "只回复 OK"
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/agent_smoke_test.py --web-search "OpenAI 当前 API 文档首页标题"
```

The web-search mode requires `--accept-billable-probe`. Output contains provider, model, enabled capabilities, latency, usage if reported, and pass/fail; it contains no raw key or authorization header.

- [ ] **Step 2: Test the script with a fake runtime**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_agent_smoke_test.py -v
```

- [ ] **Step 3: Write the runbook**

`docs/install/openai-agents-sdk.md` must include:

1. Plus versus Platform API authentication and separate billing;
2. official OpenAI, Responses proxy, and Chat-compatible configurations;
3. capability probe commands and expected exit codes;
4. remote secret-file placement and `chmod 600`;
5. OpenAI project budget/alert setup reminder;
6. local redacted telemetry location;
7. owner-private canary enablement;
8. hosted web-search enablement only after a successful probe;
9. PC Agent safety/approval boundaries;
10. rollback flags and service restart commands already used by the repository.

Do not copy a real endpoint, user key, or email credential into examples.

- [ ] **Step 4: Add a manual canary checklist**

Use this exact sequence on the remote host after code review:

```text
1. Config-only check passes with AGENT_RUNTIME_ENABLED=false.
2. Minimal text smoke test passes from the remote host.
3. Owner-private flag is enabled; group behavior is unchanged.
4. Send five ordinary private messages; confirm no tools are exposed.
5. Send one current-events request; confirm one web_search_call and visible citations.
6. Stop PC Agent; confirm a browser request fails safely.
7. Restore PC Agent; execute a read-only browser inspection.
8. Trigger an approval-required action; confirm no action executes.
9. Disable AGENT_RUNTIME_ENABLED; confirm legacy private chat works.
10. Review redacted metrics and actual API project usage before continuing.
```

- [ ] **Step 5: Run the Phase A0 test suite**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_agent_config.py \
  qq-ai-bridge/tests/test_agent_provider.py \
  qq-ai-bridge/tests/test_capability_probe.py \
  qq-ai-bridge/tests/test_agent_runtime.py \
  qq-ai-bridge/tests/test_agent_telemetry.py \
  qq-ai-bridge/tests/test_agent_tools.py \
  qq-ai-bridge/tests/test_agent_route_service.py \
  qq-ai-bridge/tests/test_pc_agent_tools.py \
  qq-ai-bridge/tests/test_private_agent_integration.py \
  qq-ai-bridge/tests/test_private_chat_service.py \
  qq-ai-bridge/tests/test_chat_skill.py \
  qq-ai-bridge/tests/test_llm_client.py \
  qq-ai-bridge/tests/test_agent_smoke_test.py -v
```

Expected: every listed test passes.

- [ ] **Step 6: Run repository checks**

```bash
bash run_ruff.sh
bash run_ruff_2.sh
git diff --check
```

Expected: both focused lint scripts and whitespace check pass. If a repository script depends on a missing local virtual environment, run it inside `qq-ai-bridge/venv` as documented in `GEMINI.md` and record the exact skipped check if it still cannot run.

- [ ] **Step 7: Commit**

```bash
git add README.md docs/install/run.md docs/install/openai-agents-sdk.md qq-ai-bridge/scripts/agent_smoke_test.py qq-ai-bridge/tests/test_agent_smoke_test.py
git commit -m "docs: add agents sdk deployment runbook"
```

## Phase A0 completion gate

Do not begin the email plan until:

- the official/proxy/chat provider distinction is visible in configuration and logs;
- the user's current third-party GPT-5.5/5.6 endpoint passes the exact capability probes for every hosted tool that will be enabled;
- Plus is not used or documented as an API credential;
- owner-private text canary passes;
- hosted web search produces a real `web_search_call` and citations;
- PC Agent tools are bounded and fail closed;
- rollback to the legacy path is verified;
- actual API usage is visible in the provider's billing dashboard.

## Official references

- [OpenAI Agents SDK quickstart](https://openai.github.io/openai-agents-python/quickstart/)
- [Models and non-OpenAI providers](https://openai.github.io/openai-agents-python/models/)
- [Hosted, local, and function tools](https://openai.github.io/openai-agents-python/tools/)
- [OpenAI web search](https://developers.openai.com/api/docs/guides/tools-web-search)
- [OpenAI computer use](https://developers.openai.com/api/docs/guides/tools-computer-use)
- [OpenAI API pricing](https://developers.openai.com/api/docs/pricing)
- [ChatGPT versus Platform billing](https://help.openai.com/en/articles/9039756-billing-settings-in-chatgpt-vs-platform)
