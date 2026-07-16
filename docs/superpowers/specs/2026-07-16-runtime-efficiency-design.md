# Runtime Efficiency Design

## Goal

Improve QQ reply latency, bound long-running resource use, and remove unnecessary per-message OpenClaw CLI launches without replacing the repository's existing skill and routing architecture.

## Delivery Order

1. Make group routing local-first so an explicit request needs only the final text-model call.
2. Introduce bounded background execution, expiring conversation state, temporary-file cleanup, and single-writer rotating logs.
3. Add a reusable direct HTTP LLM provider and retain the OpenClaw CLI as an explicit compatibility fallback.

## Group Routing

Explicit mentions, bot aliases, replies to the bot, forwarded chat records, and locally recognized questions or actions go directly to final response generation. Trivial chatter and obvious reaction candidates remain local. Only ambiguous ambient messages may call the response-mode selector.

The routing decision is represented as a small strategy hint and is included in the final prompt metadata/logs. It does not create a second response-generation request.

## Runtime Resources

A focused runtime resource service owns bounded executors for chat and media work. Per-user and per-group workers retain serial ordering, but are submitted through the shared bounded chat executor instead of creating an unbounded number of daemon threads.

Private and group state records track last activity. Idle state is removed after a configurable TTL. Pending caption records are capacity-bounded and stale entries are removed before insertion. Drawing jobs use the bounded media executor.

Startup maintenance removes stale temporary images and enforces a total-size cap. Bridge output has one file writer with size-based rotation; shell launchers no longer append the same output to the same file a second time.

The existing admin summary exposes executor capacity, active/queued work, state counts, temporary-directory size, and process RSS.

## LLM Execution

`call_ai()` remains the stable public entry point. It delegates to one of two backends:

- `direct`: OpenAI-compatible `/chat/completions` through a reused `requests.Session` and the configured DeepSeek credentials.
- `cli`: the existing `AI_CMD` OpenClaw command for compatibility or explicit agent use.

`LLM_BACKEND=auto` selects direct HTTP when an API key is configured, otherwise CLI. `LLM_BACKEND=cli` preserves the old behavior. A bounded semaphore caps simultaneous model requests. Provider failures return concise user-facing messages and keep detailed provider context in logs without exposing credentials.

## Compatibility

- Existing `call_ai()` callers and response-action parsing remain unchanged.
- Existing environment names `KIMI_*` remain accepted to avoid breaking local configuration, even when they point at DeepSeek.
- Existing skill ordering, history files, group configuration, Vision, Draw, and VoCat behavior remain intact.
- No framework migration or new third-party dependency is introduced.

## Verification

- Unit tests prove explicit group requests skip the selector while ambiguous ambient messages can still use it.
- Unit tests prove executor capacity, state expiry, runtime metrics, and direct/CLI backend selection.
- Existing group, private, draw, vision, admin, and LLM regression tests remain green.
- `git diff --check` and secret scans verify a clean patch without credentials in tracked files.
