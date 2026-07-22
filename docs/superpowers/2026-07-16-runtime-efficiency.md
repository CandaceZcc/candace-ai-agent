# Runtime Efficiency Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Reduce duplicate group-model calls, bound runtime resources, and route ordinary text generation through a reusable direct DeepSeek client instead of launching an OpenClaw CLI process per message.

**Architecture:** Preserve the current Skill and `call_ai()` boundaries. Add local-first group routing, a small bounded runtime resource service, rotating single-writer logging with startup cleanup, and direct/CLI LLM backends selected by configuration.

**Tech Stack:** Python 3.10+, standard-library `concurrent.futures`, `threading`, `logging.handlers`, `pathlib`, existing `requests`, Flask/Waitress, `unittest`.

---

### Task 1: Make explicit group requests use one model call

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/group_chat_service.py:315-422`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/group_chat_service.py:1135-1195`.
- Test: `qq-ai-bridge/tests/test_group_chat_service.py`.

- [x] **Step 1: Add failing tests.** Add a pure helper test showing an explicit trigger and a recognizable question return `{"mode": "text"}` without calling `call_ai`, while ambiguous ambient text still calls the selector.
- [x] **Step 2: Verify RED.** Run `PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest qq-ai-bridge/tests/test_group_chat_service.py -v`; expect the explicit-trigger selector assertion to fail against current behavior.
- [x] **Step 3: Implement the local-first decision.** Add `_local_group_response_mode(merged_text, batch)` and call it before constructing the selector prompt. Preserve stop-talking requests as a local silence decision. Explicit triggers, forwarded records, action/question requests, and ambient-interjection batches return text locally.
- [x] **Step 4: Verify GREEN.** Re-run the focused group service tests and confirm zero failures.

### Task 2: Add bounded runtime executors

**Files:**
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/runtime_resources.py`.
- Create: `qq-ai-bridge/tests/test_runtime_resources.py`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/config/settings.py`.

- [x] **Step 1: Add failing tests.** Test that `BoundedExecutor(max_workers=1, max_pending=1)` rejects a second outstanding job and reports `active`, `pending`, `capacity`, `submitted`, and `rejected` metrics.
- [x] **Step 2: Verify RED.** Run `PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest qq-ai-bridge/tests/test_runtime_resources.py -v`; expect import failure.
- [x] **Step 3: Implement the executor.** Use a `BoundedSemaphore(max_workers + max_pending)` around a `ThreadPoolExecutor`; release it in a future callback and update counters under a lock. Export `submit_chat_task`, `submit_media_task`, and `get_runtime_resource_status` backed by configurable singleton executors.
- [x] **Step 4: Verify GREEN.** Re-run the focused runtime resource tests.

### Task 3: Bound conversation state and background work

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/group_chat_service.py`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/private_chat_service.py`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/adapters/webhook.py`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/skills/draw.py`.
- Test: `qq-ai-bridge/tests/test_group_chat_service.py`.
- Test: `qq-ai-bridge/tests/test_private_chat_service.py`.
- Test: `qq-ai-bridge/tests/test_webhook_image_caption.py`.
- Test: `qq-ai-bridge/tests/test_draw_skill.py`.

- [x] **Step 1: Add failing tests.** Cover idle group/private state eviction after TTL, preservation of active state, caption-map capacity eviction, and draw/chat submission through runtime resources.
- [x] **Step 2: Verify RED.** Run the four focused test modules and confirm failures are caused by missing TTL/bounded submission behavior.
- [x] **Step 3: Implement minimal lifecycle behavior.** Add `last_activity_monotonic` to conversation states, clean idle entries opportunistically, replace direct chat/draw `threading.Thread` creation with bounded executor submission, and evict stale/oldest caption entries before insertion.
- [x] **Step 4: Verify GREEN.** Re-run the focused lifecycle tests.

### Task 4: Rotate logs, clean temporary images, and expose health metrics

**Files:**
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/runtime_maintenance.py`.
- Create: `qq-ai-bridge/tests/test_runtime_maintenance.py`.
- Modify: `qq-ai-bridge/bridge.py`.
- Modify: `runai.sh`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/adapters/admin_ui.py`.
- Modify: `qq-ai-bridge/tests/test_admin_console.py`.

- [x] **Step 1: Add failing tests.** Test age and size-based temporary-file cleanup and verify the admin summary contains `runtime_resources`, `temporary_storage`, and `process_rss_bytes`.
- [x] **Step 2: Verify RED.** Run the runtime maintenance and admin tests; expect missing symbols/fields.
- [x] **Step 3: Implement maintenance and logging.** Use `RotatingFileHandler` through a text stream adapter in `bridge.py`, remove `tee -a`/shell redirection to the same bridge log, run temporary cleanup at startup, and merge safe runtime metrics into `_build_summary()`.
- [x] **Step 4: Verify GREEN.** Re-run focused tests and use a shell assertion to confirm the launcher no longer contains a second bridge-log append pipeline.

### Task 5: Add direct and CLI LLM backends

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/config/settings.py`.
- Modify: `qq-ai-bridge/.env.example`.
- Modify: `qq-ai-bridge/shared/ai/llm_client.py`.
- Modify: `qq-ai-bridge/tests/test_llm_client.py`.
- Modify: `qq-ai-bridge/tests/test_kimi_config_defaults.py`.

- [x] **Step 1: Add failing tests.** Verify `auto` selects direct HTTP when the key is present, direct requests reuse a session and send the configured model, `cli` still invokes `AI_CMD`, and an occupied model semaphore returns a busy message without launching either backend.
- [x] **Step 2: Verify RED.** Run the LLM/config tests and confirm backend-selection assertions fail.
- [x] **Step 3: Implement backend selection.** Add `LLM_BACKEND`, `LLM_MAX_CONCURRENCY`, and `LLM_QUEUE_TIMEOUT_SECONDS`; reuse a module-level `requests.Session`; make `call_ai()` acquire the semaphore and delegate to `_call_direct_llm` or `_call_cli_llm`; keep `call_kimi_text()` as a compatibility wrapper around the direct client.
- [x] **Step 4: Verify GREEN.** Re-run LLM/config tests and confirm the CLI compatibility path remains covered.

### Task 6: Full regression verification

**Files:**
- Inspect all modified files and the final diff.

- [x] **Step 1: Run the complete bridge test suite.** Run `PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest discover -s qq-ai-bridge/tests -p 'test_*.py'` and require zero failures/errors.
- [x] **Step 2: Run lint/syntax checks.** Run `.venv/bin/python -m compileall -q qq-ai-bridge/apps qq-ai-bridge/shared qq-ai-bridge/vision` and `.venv/bin/ruff check` on modified Python files when Ruff is installed.
- [x] **Step 3: Inspect repository hygiene.** Run `git diff --check`, inspect `git status --short`, and scan tracked diffs for API-key patterns without printing local secret files.
- [x] **Step 4: Report results without committing unrelated existing work.** Leave the user's existing uncommitted Gemini/Draw changes intact and identify every modified file and remaining operational restart step.
