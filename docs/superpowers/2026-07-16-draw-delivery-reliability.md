# Draw Delivery Reliability Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `/draw` survive transient Right Codes polling failures, wait long enough for real generation, fall back to `gpt-image-2`, and deliver the resulting image to QQ.

**Architecture:** Keep the existing `DrawResult` service boundary and QQ skill. Harden the shared asynchronous task poller, add an OpenAI Images-compatible submission adapter, and orchestrate primary/fallback providers inside `generate_image`. Use safe state-transition logs and verify with a real local webhook that sends an image through NapCat.

**Tech Stack:** Python 3, `requests`, Pillow, `unittest.mock`, Flask webhook, NapCat OneBot HTTP API.

---

## File Map

- Modify `qq-ai-bridge/apps/qq_ai_bridge/config/settings.py`: draw retry, deadline, and fallback settings.
- Modify `qq-ai-bridge/apps/qq_ai_bridge/services/draw_service.py`: resilient polling, Images payload/submission, fallback orchestration, safe logs.
- Modify `qq-ai-bridge/apps/qq_ai_bridge/skills/draw.py`: worker exception containment and final delivery logs.
- Modify `qq-ai-bridge/.env.example`: non-secret draw configuration documentation.
- Modify `/home/cancade/.candace/qq-ai-bridge.env`: machine-local runtime values only.
- Modify `qq-ai-bridge/tests/test_draw_service.py`: polling and fallback regression tests.
- Modify `qq-ai-bridge/tests/test_draw_skill.py`: worker exception and delivery tests.
- Modify `qq-ai-bridge/tests/test_kimi_config_defaults.py`: configuration defaults.

### Task 1: Make asynchronous polling resilient

**Files:**
- Modify: `qq-ai-bridge/tests/test_draw_service.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/draw_service.py`

- [ ] **Step 1: Add failing polling tests**

Add tests that model the observed production behavior:

```python
@patch("apps.qq_ai_bridge.services.draw_service.requests.get")
def test_poll_draw_retries_transient_http_failure_then_completes(self, mock_get):
    retry = MagicMock(ok=False, status_code=502)
    completed = MagicMock(ok=True, status_code=200)
    completed.json.return_value = {
        "candidates": [{"content": {"parts": [{"text": "https://cdn.example.com/result.png"}]}}]
    }
    mock_get.side_effect = [retry, completed]

    result = poll_draw(
        "task-123",
        api_key="sk-test",
        base_url="https://www.right.codes",
        timeout_seconds=240,
        poll_interval_seconds=0,
        max_transient_errors=2,
        sleep_fn=lambda _seconds: None,
    )

    self.assertEqual(result.status, "completed")
    self.assertEqual(mock_get.call_count, 2)
```

Also cover a `requests.Timeout` followed by success, `pending`/`running` intermediate states, and retry-budget exhaustion.

- [ ] **Step 2: Run the focused tests and verify RED**

Run:

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest \
  qq-ai-bridge/tests/test_draw_service.py
```

Expected: new tests fail because `poll_draw` lacks `max_transient_errors` and returns immediately on transient errors.

- [ ] **Step 3: Implement bounded transient retries**

Update `poll_draw` to accept `max_transient_errors`, recognize transient HTTP codes, reset the consecutive counter after a successful response, and treat the complete pending-status set as non-terminal:

```python
_PENDING_STATUSES = {"queued", "pending", "processing", "running", "in_progress"}
_TRANSIENT_HTTP_STATUSES = {408, 409, 425, 429}

def _is_transient_http_status(status_code: int) -> bool:
    return status_code in _TRANSIENT_HTTP_STATUSES or status_code >= 500
```

Network exceptions and transient HTTP responses retry until the budget or overall deadline is exhausted. Log only provider/model, shortened task ID, status, retry count, and HTTP status.

- [ ] **Step 4: Run the focused tests and verify GREEN**

Run the Task 1 command. Expected: all draw-service tests pass.

### Task 2: Add Image2 fallback orchestration

**Files:**
- Modify: `qq-ai-bridge/tests/test_draw_service.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/draw_service.py`

- [ ] **Step 1: Add failing Images adapter tests**

Add concrete tests for this payload and endpoint:

```python
payload = build_images_payload(
    "原创黄色卡通机器人",
    model="gpt-image-2",
    aspect_ratio="1:1",
    image_size="1K",
)
self.assertEqual(payload, {
    "model": "gpt-image-2",
    "prompt": "原创黄色卡通机器人",
    "n": 1,
    "size": "1:1",
    "imageSize": "1K",
    "async": True,
})
```

Test `POST https://www.right.codes/draw/v1/images/generations`, optional reference data URL, primary success without fallback, and primary terminal failure invoking fallback exactly once.

- [ ] **Step 2: Run the new tests and verify RED**

Run the draw-service test file. Expected: missing `build_images_payload`/`submit_images_draw` and no fallback call.

- [ ] **Step 3: Implement the Images adapter and provider sequence**

Add:

```python
def build_images_payload(...): ...
def submit_images_draw(...): ...
def _generate_with_gemini(...): ...
def _generate_with_images(...): ...
```

`generate_image` prepares the reference image once, calls Banana first, and calls Image2 only when fallback is enabled and the primary result is not completed. Preserve the final provider/model/task/error metadata on `DrawResult`.

- [ ] **Step 4: Run the draw-service tests and verify GREEN**

Run the Task 1 command. Expected: all tests pass with primary and fallback paths covered.

### Task 3: Add configuration and worker safety

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/config/settings.py`
- Modify: `qq-ai-bridge/.env.example`
- Modify: `qq-ai-bridge/tests/test_kimi_config_defaults.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/skills/draw.py`
- Modify: `qq-ai-bridge/tests/test_draw_skill.py`

- [ ] **Step 1: Add failing configuration and worker tests**

Assert defaults:

```python
self.assertEqual(settings.DRAW_TIMEOUT_SECONDS, 240)
self.assertEqual(settings.DRAW_POLL_MAX_TRANSIENT_ERRORS, 6)
self.assertEqual(settings.DRAW_FALLBACK_MODEL, "gpt-image-2")
self.assertTrue(settings.DRAW_FALLBACK_ENABLED)
```

Add a worker test where `generate_image` raises and verify the user receives one terminal error instead of losing the background exception.

- [ ] **Step 2: Run focused tests and verify RED**

Run:

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest \
  qq-ai-bridge/tests/test_kimi_config_defaults.py \
  qq-ai-bridge/tests/test_draw_skill.py
```

Expected: missing settings and uncaught worker exception.

- [ ] **Step 3: Implement settings and exception containment**

Load the new settings with existing helpers, document blank/non-secret defaults, and wrap `_run_draw_worker` so unexpected exceptions produce a safe `[DRAW]` warning plus `画图失败了，稍后再试。`.

- [ ] **Step 4: Update machine-local runtime configuration**

Set without printing secrets:

```dotenv
DRAW_TIMEOUT_SECONDS=240
DRAW_POLL_MAX_TRANSIENT_ERRORS=6
DRAW_FALLBACK_MODEL=gpt-image-2
DRAW_FALLBACK_ENABLED=true
```

- [ ] **Step 5: Run focused tests and verify GREEN**

Run the Task 3 command. Expected: all tests pass.

### Task 4: Regression verification and live QQ delivery

**Files:**
- Verify: all modified files above
- Runtime logs: `.runtime/logs/bridge.log`
- Outbound events: `qq-ai-bridge/data/logs/napcat_outbound.jsonl`

- [ ] **Step 1: Run focused regressions**

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest \
  qq-ai-bridge/tests/test_draw_service.py \
  qq-ai-bridge/tests/test_draw_skill.py \
  qq-ai-bridge/tests/test_napcat_client.py \
  qq-ai-bridge/tests/test_kimi_config_defaults.py \
  qq-ai-bridge/tests/test_runtime_resources.py
```

Expected: zero failures and zero errors.

- [ ] **Step 2: Run repository lint for touched service/skill files**

```bash
bash run_ruff.sh
bash run_ruff_2.sh
```

Expected: exit status 0, or report any pre-existing unrelated lint failures separately.

- [ ] **Step 3: Restart the bridge**

Stop only the active bridge process, start it with the repository launcher, and confirm the startup log loaded `/home/cancade/.candace/qq-ai-bridge.env`.

- [ ] **Step 4: Trigger a real private QQ `/draw` webhook**

Post a OneBot private-message event containing a neutral original-character prompt to `http://127.0.0.1:5000/qq-webhook`, using the owner's existing QQ user ID and the configured bot self ID.

- [ ] **Step 5: Verify provider and QQ delivery**

Require all of the following evidence:

- Right Codes task reaches `completed` for Banana or Image2.
- `[DRAW]` log records completed status without secrets.
- `napcat_outbound.jsonl` contains a real `type: image`, real owner user ID, `ok: true`, and provider image URL.
- The user confirms the image is visible in QQ if local logs cannot prove rendering.

- [ ] **Step 6: Review final diff**

Run `git diff --check` and inspect `git diff` to ensure no unrelated user changes were overwritten.

