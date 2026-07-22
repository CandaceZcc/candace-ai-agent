# Group Chat Coherence Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the seven confirmed causes of disconnected group-chat replies while keeping real local-file, secret-exfiltration, and destructive-command requests blocked before any model call.

**Architecture:** Turn the existing `chat_log.json` into a backward-compatible chronological event stream: capture configured inbound group messages before routing, record successful assistant actions separately, and render both old combined records and new role-based records into prompts. Add semantic safety classification, stale-reply cancellation, one canonical data root, one coherent persona layer, and silent/retry handling for empty provider output without changing private chat, email delivery, or 6657 matching behavior.

**Tech Stack:** Python 3.10+, Flask webhook, existing OneBot/NapCat adapters, `requests`, JSON file storage, `threading`, `unittest`.

---

## Confirmed Issue Coverage

| Issue | Planned task |
|---|---|
| 1. Prompt history drops assistant replies | Task 2 |
| 2. `capture_all_messages` does not capture ignored/silent messages | Task 1 |
| 3. Secret words trigger without dangerous intent | Task 3 |
| 4. Delayed replies are sent after a correction/follow-up | Task 4 |
| 5. Persona layers conflict and post-processing forces `喵` | Task 5 |
| 6. Style capture writes to a different data root | Task 6 |
| 7. Empty provider output becomes visible diagnostic text | Task 7 |

### Task 1: Capture a complete inbound group timeline

**Files:**
- Modify: `qq-ai-bridge/storage_utils.py`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/adapters/webhook.py`.
- Test: `qq-ai-bridge/tests/test_group_timeline.py`.
- Test: `qq-ai-bridge/tests/test_webhook_image_caption.py`.

- [ ] **Step 1: Write failing storage and webhook tests.** Cover an enabled group with `capture_all_messages=true` and verify ordinary text is persisted before skill dispatch even when the eventual strategy is silence, addressed to another person, or cooldown-limited. Verify disabled/ignored groups and groups with capture disabled are not persisted.

- [ ] **Step 2: Define the role-based event shape.** New inbound entries must use this backward-compatible schema and must never contain environment values, model credentials, or local file contents:

```python
{
    "timestamp": 1784627000,
    "role": "user",
    "sender_name": "群友A",
    "user_id": 10001,
    "message": "何意味",
    "message_id": 123456,
    "source": "group_inbound",
}
```

- [ ] **Step 3: Make appends concurrency-safe.** Add a per-path lock around the read/append/trim/write sequence used by `append_group_chat_log()` so simultaneous webhook and worker writes cannot overwrite each other. Keep the current 500-entry cap and existing JSON format.

- [ ] **Step 4: Capture at the routing boundary.** In `SkillDispatcher.dispatch()`, after loading and accepting group configuration but before style capture and `dispatch_skill()`, append one normalized inbound event when `capture_all_messages` is true. Preserve `message_id`, sender, user, and event timestamp; represent an image-only event as `[图片]`, but do not duplicate a text caption when the five-second image-caption merge redispatches the same `message_id`.

- [ ] **Step 5: Verify RED then GREEN.** Run:

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest \
  qq-ai-bridge/tests/test_group_timeline.py \
  qq-ai-bridge/tests/test_webhook_image_caption.py -v
```

Before implementation, expect missing timeline entries; after implementation, require zero failures and confirm a silence decision still leaves the inbound event available to later prompts.

### Task 2: Render human and assistant events in chronological prompts

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/prompt_service.py`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/group_chat_service.py`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/skills/chat.py`.
- Test: `qq-ai-bridge/tests/test_prompt_service.py`.
- Test: `qq-ai-bridge/tests/test_group_chat_service.py`.
- Test: `qq-ai-bridge/tests/test_chat_skill.py`.

- [ ] **Step 1: Write failing history tests.** Add a reproduction with the old combined record `{message: "深圳吗", assistant: "深圳？你咋突然问这个"}` followed by `{message: "何意味"}`. Assert the rendered prompt contains the user line, assistant line, and follow-up in timestamp order. Add a second fixture using new separate `role=user` and `role=assistant` events.

- [ ] **Step 2: Render both schemas without duplication.** Refactor `_build_group_history_lines()` so old records emit up to two lines and new records emit one role-specific line. Use a stable assistant label such as `机盖宁` and preserve image classification hints. Apply the character budget to complete chronological events and keep the newest event when one event alone exceeds the budget.

- [ ] **Step 3: Record successful assistant text as its own event.** When `capture_all_messages` is true, replace the worker's combined user/assistant write with an assistant event containing actual send time, reply target, text, and source. Apply the same rule to local safety responses, repeat-follow responses, generated-file notices, and 6657 text; when capture is false, preserve the existing combined record for compatibility.

```python
{
    "timestamp": 1784627004,
    "role": "assistant",
    "sender_name": "机盖宁",
    "assistant": "深圳？你咋突然问这个",
    "reply_to_message_id": 123456,
    "source": "group_chat",
}
```

- [ ] **Step 4: Base compact/full selection on message content.** Derive `query_len` from `batch_context["merged_blocks"][].texts` rather than the sender-prefixed `prompt_text`; continue passing sender names in the actual current-message section. Assert `群友A：何意味` selects compact mode because the semantic query is three characters.

- [ ] **Step 5: Expand recent context by events and time.** Replace the fixed 2/4-record interpretation with at most 10 events in compact mode and 16 events in full mode, bounded to the most recent three minutes and existing character budgets. Do not pull old unrelated conversations merely to fill the event count.

- [ ] **Step 6: Verify focused context behavior.** Run:

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest \
  qq-ai-bridge/tests/test_prompt_service.py \
  qq-ai-bridge/tests/test_group_chat_service.py \
  qq-ai-bridge/tests/test_chat_skill.py -v
```

Require tests for old logs, new events, silent inbound messages, assistant replies, compact-mode selection, time expiry, event limits, and character limits to pass.

### Task 3: Require dangerous intent for secret and file blocking

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/group_chat_service.py`.
- Test: `qq-ai-bridge/tests/test_group_chat_service.py`.

- [ ] **Step 1: Add negative regression tests.** Assert `_build_group_safety_action()` returns `None` for `这个模型比较耗 token`, `除了耗时和耗 token 没缺点`, `token 数量怎么算`, `密码学这门课难吗`, and forwarded/quoted records that merely contain the word `密码`.

- [ ] **Step 2: Preserve positive security tests.** Keep hard-block assertions for requests to send `API_KEY`, read or export `.env`, list protected local files, send protected absolute-path files, delete/format paths, and execute shutdown/reboot commands.

- [ ] **Step 3: Split the matcher into explicit categories.** Replace the single catch-all regex with pure helpers for destructive system actions, protected local file operations, secret objects, and disclosure/read actions. A secret-related request blocks only when both a secret object and a disclosure/read action are present; destructive commands and explicit protected-path export remain independently blocked.

```python
def _is_dangerous_file_or_secret_request(text: str) -> bool:
    if _looks_like_forwarded_chat_record(text):
        return False
    if _DESTRUCTIVE_SYSTEM_ACTION_PATTERN.search(text):
        return True
    if _PROTECTED_FILE_OPERATION_PATTERN.search(text):
        return True
    return bool(
        _SECRET_OBJECT_PATTERN.search(text)
        and _SECRET_ACCESS_INTENT_PATTERN.search(text)
    )
```

- [ ] **Step 4: Keep the local block before the model.** Do not lower the priority of confirmed dangerous requests. Log only the rule category (`destructive_action`, `protected_file_operation`, or `secret_exfiltration`), never the matched secret or local file contents.

- [ ] **Step 5: Verify focused safety behavior.** Run `PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest qq-ai-bridge/tests/test_group_chat_service.py -v` and require all positive and negative cases to pass.

### Task 4: Cancel stale replies when related messages arrive

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/group_chat_service.py`.
- Test: `qq-ai-bridge/tests/test_group_chat_service.py`.

- [ ] **Step 1: Add deterministic stale-reply tests.** While a mocked `call_ai()` is in progress, enqueue a same-user correction and assert the old reply is not sent. Cover a same-user follow-up, a reply referencing the original message ID, and an unrelated message from another user that must not cancel a quoted response.

- [ ] **Step 2: Add a group-state revision.** Increment `GroupChatState.revision` for every enqueue. Capture the revision and batch message IDs immediately before model generation, then inspect pending messages under `state.lock` before any text send.

- [ ] **Step 3: Define a narrow supersession rule.** Treat a newer pending message as related when it comes from a batch participant, replies to a batch message ID, or explicitly targets the bot while the current batch is being answered. If related, discard the generated text and continue the worker loop; the newer pending batch will regenerate against the complete inbound timeline. Do not requeue the old batch and do not cancel for unrelated ambient traffic.

- [ ] **Step 4: Check twice around artificial delay.** Run the stale check once after parsing/humanizing model output and again after `strategy_delay`, immediately before `execute_group_action()`. Emit a structured `stale_reply_cancelled` trace containing only group ID, revision, and message IDs.

- [ ] **Step 5: Verify timing behavior.** Run the focused group-service tests and assert no stale text reaches `execute_group_action()`, the correction remains pending, and an unrelated message still allows a reply quoted to its original target.

### Task 5: Make persona instructions coherent and stop forced suffixes

**Files:**
- Modify: `qq-ai-bridge/data/group_uploads/SOUL.md` locally.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/prompt_service.py`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/group_chat_service.py`.
- Test: `qq-ai-bridge/tests/test_prompt_service.py`.
- Test: `qq-ai-bridge/tests/test_group_chat_service.py`.

- [ ] **Step 1: Add persona and post-processing tests.** Assert the effective prompt contains one consistent hierarchy: privacy/safety, understand context, answer serious questions, then casual style. Assert it excludes `宁可骂错`, `只骂不解释`, and `被骂必反击`. Assert `_humanize_group_reply("大概需要两分钟", ...)` does not mechanically append `喵`.

- [ ] **Step 2: Rewrite the local SOUL rules.** Preserve short, casual, meme-aware group speech and friendly reciprocal `喵`, but remove instructions that reward incorrect abuse, refuse explanations, or contradict serious-question handling. Keep privacy refusal and the distinction between casual banter and genuine questions.

- [ ] **Step 3: Simplify prompt composition.** Make baseline safety and context accuracy authoritative; make SOUL and learned style optional tone guidance that cannot override them. Remove `可以骂人` from the fallback persona and remove duplicated aggression/length rules that conflict with `silent_strategy`.

- [ ] **Step 4: Remove unconditional `喵` injection.** Delete or narrow `_soften_plain_group_answer()` so it never rewrites an otherwise valid factual answer solely to add a suffix. Keep explicit greeting handling and allow the model/style profile to choose `喵` naturally from context.

- [ ] **Step 5: Verify persona behavior.** Run prompt and group-service tests, then inspect generated prompts for compact and full modes to ensure there are no truncated control tokens such as partial `NO_REPLY` instructions.

### Task 6: Use one canonical style-data root

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/adapters/webhook.py`.
- Test: `qq-ai-bridge/tests/test_group_timeline.py`.
- Test: `qq-ai-bridge/tests/test_prompt_service.py`.

- [ ] **Step 1: Add a failing data-root test.** Patch `BASE_DATA_DIR` to a temporary directory, dispatch a style-learning group event, and assert `capture_group_style()` receives that exact directory rather than the relative string `data`.

- [ ] **Step 2: Pass the configured root everywhere.** Import `BASE_DATA_DIR` from settings in `webhook.py` and replace `capture_group_style("data", ...)` with `capture_group_style(BASE_DATA_DIR, ...)`. Confirm prompt history, inbound events, assistant events, and style profiles all resolve through the same setting.

- [ ] **Step 3: Preserve canonical existing data.** Treat the `BASE_DATA_DIR` resolved by the retained workspace as canonical for the current runtime. Do not overwrite its larger existing profile with the smaller worktree-relative profile; after restart, new samples must update only the canonical profile.

- [ ] **Step 4: Verify directory behavior.** Run the focused timeline/prompt tests and a runtime smoke check comparing the configured `BASE_DATA_DIR` with the paths logged for history and style updates. Do not print environment-file contents.

### Task 7: Retry or silence empty provider output

**Files:**
- Modify: `qq-ai-bridge/shared/ai/llm_client.py`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/group_chat_service.py`.
- Test: `qq-ai-bridge/tests/test_llm_client.py`.
- Test: `qq-ai-bridge/tests/test_group_chat_service.py`.

- [ ] **Step 1: Add empty-response tests.** Mock a successful HTTP response with usage tokens but empty `message.content`. Assert the direct client retries once, returns real content if the retry succeeds, and returns an empty string after two empty responses. Assert `模型没有返回内容` is never returned or sent.

- [ ] **Step 2: Keep reasoning private.** If the provider returns only `reasoning_content`, record only an `empty_visible_content` diagnostic and usage metadata; do not send hidden reasoning to QQ and do not dump the raw provider body or credentials to logs.

- [ ] **Step 3: Make empty output a no-reply action.** Return `""` from `_call_direct_llm()` after the bounded retry. Let `parse_llm_response_action()` produce `NO_REPLY(reason="empty_reply")`, and exclude `empty_reply` and upstream-service failures from `_build_explicit_trigger_no_reply_fallback()` so diagnostics are not converted into chat text.

- [ ] **Step 4: Verify focused LLM behavior.** Run:

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest \
  qq-ai-bridge/tests/test_llm_client.py \
  qq-ai-bridge/tests/test_group_chat_service.py -v
```

Require retry-success, retry-exhaustion, hidden-reasoning, explicit-trigger, and ambient-message cases to pass.

### Task 8: Full verification, privacy audit, and runtime rollout

**Files:**
- Inspect all modified source, tests, prompt files, configuration, and runtime logs.
- Do not add `qq-ai-bridge/data/groups/**`, style profiles, bridge logs, or `${HOME}/.candace/qq-ai-bridge.env` to Git.

- [ ] **Step 1: Run the complete bridge suite.** Run:

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest discover \
  -s qq-ai-bridge/tests -p 'test_*.py'
```

Require zero failures and zero errors.

- [ ] **Step 2: Run syntax and diff checks.** Run `.venv/bin/python -m compileall -q qq-ai-bridge/apps qq-ai-bridge/shared qq-ai-bridge/storage_utils.py`, `git diff --check`, and focused Ruff checks only if Ruff is already installed.

- [ ] **Step 3: Audit sensitive and runtime files.** Use `git status --short` and `git diff --cached --name-only` to confirm no env file, key, raw group history, style profile, or runtime log is tracked. Scan tracked diffs for secret-like assignments without printing any secret values.

- [ ] **Step 4: Perform an independent review thread.** Without editing, review requirements completeness, logic correctness, edge cases, code quality, test coverage, and actual runtime evidence. Feed concrete findings back into the implementation thread and rerun affected checks after any fixes.

- [ ] **Step 5: Restart without changing secrets.** Restart the bridge through the existing launcher on the retained branch, preserving the machine-local env and canonical `BASE_DATA_DIR`. Confirm the active process loads the edited source and does not start a duplicate bridge.

- [ ] **Step 6: Run a compact group smoke matrix.** In the approved test group, verify: a normal `token` discussion is not blocked; a real API-key export request is blocked locally; an ignored message appears in the next prompt context; a follow-up resolves the bot's previous sentence; a correction cancels an old delayed reply; an ordinary factual answer is not forced to end in `喵`; and two empty model responses produce no visible diagnostic.

- [ ] **Step 7: Observe logs for one normal conversation window.** Confirm `history_items` includes human and assistant events, `stale_reply_cancelled` appears only for related follow-ups, style writes and prompt reads share one path, and no sensitive message body is emitted by new diagnostics.
