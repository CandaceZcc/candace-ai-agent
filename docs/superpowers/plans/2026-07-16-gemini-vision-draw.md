# Gemini Vision and `/draw` Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect image understanding to RightCodes Gemini 3 Flash Preview and add an asynchronous `/draw` command that sends generated images back to QQ.

**Architecture:** Keep the existing Vision client boundary, but switch its request/response adapter to Gemini native `generateContent`. Add a focused draw service for RightCodes async submission/polling, a high-priority `DrawSkill`, and explicit NapCat image-segment send helpers. Runtime secrets are loaded from the existing machine-local env file; the committed template contains empty key values.

**Tech Stack:** Python 3.10+, `requests`, Pillow, Flask webhook, OneBot/NapCat HTTP API, `unittest`.

---

### Task 1: Configure Gemini Vision and adapt the Vision client

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/config/settings.py:264-310` to add Draw defaults alongside existing model settings.
- Modify: `qq-ai-bridge/.env.example:3-8,56-59` to document Gemini Vision and Draw variables without real keys.
- Modify: `qq-ai-bridge/vision/client.py` to build Gemini-native requests and parse Gemini candidates.
- Test: `qq-ai-bridge/tests/test_vision_client.py`.
- Test: `qq-ai-bridge/tests/test_kimi_config_defaults.py` for the committed template and defaults.

- [ ] **Step 1: Write the failing Vision request tests.** Add tests that patch `requests.post`, set `VISION_API_URL=https://right.codes/gemini/v1beta/models/gemini-3-flash-preview:generateContent`, and assert the request uses `x-goog-api-key`, no Bearer header, `contents[].parts[].inline_data`, and extracts `candidates[0].content.parts[0].text`.

- [ ] **Step 2: Run the Vision tests and verify the expected failure.**

Run:

```bash
PYTHONPATH=qq-ai-bridge qq-ai-bridge/venv/bin/python -m unittest qq-ai-bridge/tests/test_vision_client.py
```

Expected: the new header/payload assertions fail because the current client sends OpenAI `messages` and a Bearer header.

- [ ] **Step 3: Implement the Gemini-native adapter.** Preserve `VisionResult`, image normalization, cleanup, and existing status mapping. Change request headers to `x-goog-api-key`, build:

```python
{
    "contents": [{
        "role": "user",
        "parts": [
            {"text": build_vision_prompt(user_text)},
            {"inline_data": {"mime_type": mime_type, "data": encoded}},
        ],
    }],
}
```

Parse text parts from `candidates[].content.parts[]`, while retaining the existing `reply`, `text`, and OpenAI choices fallbacks for compatibility with older relay responses.

- [ ] **Step 4: Run the Vision tests and verify they pass.**

Run the same command from Step 2. Expected: all Vision client tests pass.

- [ ] **Step 5: Commit the isolated Vision change if the repository index is writable.**

```bash
git add qq-ai-bridge/vision/client.py qq-ai-bridge/tests/test_vision_client.py qq-ai-bridge/.env.example qq-ai-bridge/apps/qq_ai_bridge/config/settings.py qq-ai-bridge/tests/test_kimi_config_defaults.py
git commit -m "feat: use RightCodes Gemini for vision"
```

If `.git/index` remains read-only, leave the files staged/unstaged and report that commit was skipped; do not modify unrelated work.

### Task 2: Add the RightCodes asynchronous drawing service

**Files:**
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/draw_service.py`.
- Create: `qq-ai-bridge/tests/test_draw_service.py`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/config/settings.py` to add `DRAW_*` defaults and `DRAW_API_KEY` fallback behavior.
- Modify: `qq-ai-bridge/.env.example` to document `DRAW_*` values with an empty key.

- [ ] **Step 1: Write failing draw-service tests.** Add separate tests named `test_build_draw_payload_uses_gemini_async_shape`, `test_submit_draw_returns_task_id`, `test_poll_draw_extracts_completed_gemini_image_url`, `test_poll_draw_returns_failed_status_without_retrying`, and `test_poll_draw_times_out_after_deadline`. Each test must assert one behavior and use concrete mocked JSON responses from the approved design.

Patch `requests.post`, `requests.get`, and the injected clock/sleep helper; assert that submit uses `Authorization: Bearer`, `/draw/v1beta/models/{model}:generateContent`, `async: true`, and that polling uses `/v1/tasks/{task_id}`.

- [ ] **Step 2: Run the new draw tests and verify they fail for missing service symbols.**

```bash
PYTHONPATH=qq-ai-bridge qq-ai-bridge/venv/bin/python -m unittest qq-ai-bridge/tests/test_draw_service.py
```

Expected: import or assertion failures because the service does not exist yet.

- [ ] **Step 3: Implement `draw_service.py`.** Expose `DrawResult`, `build_draw_payload`, `submit_draw`, `poll_draw`, and `generate_image`. Use defaults `DRAW_BASE_URL=https://www.right.codes`, `DRAW_MODEL=nano-banana-2`, `DRAW_ASPECT_RATIO=1:1`, `DRAW_IMAGE_SIZE=1K`, `DRAW_POLL_INTERVAL_SECONDS=2`, and `DRAW_TIMEOUT_SECONDS=90`. Resolve the key as `DRAW_API_KEY` first, then `VISION_API_KEY`. For a reference image, download it, normalize it with Pillow, and include a `contents[].parts[].inline_data` part. Never include the key in logs or error text.

- [ ] **Step 4: Run the draw tests and verify they pass.**

```bash
PYTHONPATH=qq-ai-bridge qq-ai-bridge/venv/bin/python -m unittest qq-ai-bridge/tests/test_draw_service.py
```

Expected: all new draw-service tests pass.

### Task 3: Add NapCat image-segment sending

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/adapters/napcat_client.py` next to `send_private_msg` and `send_group_msg`.
- Modify: `qq-ai-bridge/tests/test_napcat_client.py`.

- [ ] **Step 1: Write failing tests for `send_private_image` and `send_group_image`.** Assert the payload message is `[{"type": "image", "data": {"file": image_url}}]`; for groups, assert an optional reply segment precedes the image segment.

- [ ] **Step 2: Run the focused NapCat tests and verify the new assertions fail.**

```bash
PYTHONPATH=qq-ai-bridge qq-ai-bridge/venv/bin/python -m unittest qq-ai-bridge/tests/test_napcat_client.py
```

- [ ] **Step 3: Implement the two image helpers.** Reuse `_post_json`, outbound event logging, and existing return-shape conventions. Treat an HTTP or OneBot nonzero return code as failure and return a structured `{"ok": False, "error": "napcat_image_send_failed"}` result with available status metadata.

- [ ] **Step 4: Re-run the focused NapCat tests and verify they pass.**

### Task 4: Add `/draw` routing and asynchronous delivery

**Files:**
- Create: `qq-ai-bridge/apps/qq_ai_bridge/skills/draw.py`.
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/skills/registry.py` to register `DrawSkill` before `ImageUnderstandingSkill`.
- Create: `qq-ai-bridge/tests/test_draw_skill.py`.

- [ ] **Step 1: Write failing skill tests.** Add separate tests named `test_draw_skill_matches_draw_anywhere_in_message`, `test_draw_skill_uses_text_after_first_draw_as_prompt`, `test_draw_skill_replies_with_usage_for_empty_prompt`, `test_draw_skill_starts_worker_and_returns_handled`, and `test_draw_skill_sends_image_to_private_or_group_target`. Build real `SkillContext` objects and assert the exact prompt, status, target ID, image URL, and reply message ID.

Mock `threading.Thread`, `generate_image`, `send_private_msg`, `send_group_msg`, `send_private_image`, and `send_group_image`. Assert normal image/chat skills are not selected when `/draw` is present.

- [ ] **Step 2: Run the skill tests and verify they fail before implementation.**

```bash
PYTHONPATH=qq-ai-bridge qq-ai-bridge/venv/bin/python -m unittest qq-ai-bridge/tests/test_draw_skill.py
```

- [ ] **Step 3: Implement `DrawSkill`.** Match a literal `/draw` occurrence in `context.effective_text`; use the trimmed suffix as the prompt. For an empty prompt, send `用法：/draw 你想画的内容`. For a valid prompt, send `正在画，稍等一下。`, launch a daemon worker, and return `SkillResult(handled=True, source="draw", status="queued")`. The worker calls `generate_image`, sends the image segment to the original target with `reply_to_message_id` for groups, and falls back to the result URL as text if image sending fails. If the context has an image URL, pass the first URL to `generate_image` as a reference image.

- [ ] **Step 4: Register the skill before image understanding and chat.** Keep the existing skill order for all other messages.

- [ ] **Step 5: Run the skill tests and verify they pass.**

### Task 5: Configure the machine-local API and run regression verification

**Files:**
- Modify: `/home/cancade/.candace/qq-ai-bridge.env` with the user-provided RightCodes key, Gemini Vision URL/model, and Draw defaults. Do not write the key to tracked files.
- Modify: `qq-ai-bridge/.env.example` with blank `VISION_API_KEY` and `DRAW_API_KEY` entries plus the non-secret defaults.

- [ ] **Step 1: Update the local env without printing secret values.** Set:

```dotenv
VISION_API_URL=https://right.codes/gemini/v1beta/models/gemini-3-flash-preview:generateContent
VISION_API_KEY=
VISION_MODEL=gemini-3-flash-preview
DRAW_API_KEY=
DRAW_BASE_URL=https://www.right.codes
DRAW_MODEL=nano-banana-2
DRAW_ASPECT_RATIO=1:1
DRAW_IMAGE_SIZE=1K
DRAW_POLL_INTERVAL_SECONDS=2
DRAW_TIMEOUT_SECONDS=90
```

Assign `VISION_API_KEY` from the credential supplied in this conversation without printing it. `DRAW_API_KEY` remains empty so the service falls back to `VISION_API_KEY`.

- [ ] **Step 2: Run focused regression tests.**

```bash
PYTHONPATH=qq-ai-bridge qq-ai-bridge/venv/bin/python -m unittest \
  qq-ai-bridge/tests/test_vision_client.py \
  qq-ai-bridge/tests/test_draw_service.py \
  qq-ai-bridge/tests/test_draw_skill.py \
  qq-ai-bridge/tests/test_napcat_client.py \
  qq-ai-bridge/tests/test_kimi_config_defaults.py \
  qq-ai-bridge/tests/test_llm_client.py
```

Expected: zero failures and zero errors.

- [ ] **Step 3: Run the image/webhook regression tests.**

```bash
PYTHONPATH=qq-ai-bridge qq-ai-bridge/venv/bin/python -m unittest \
  qq-ai-bridge/tests/test_image_understanding.py \
  qq-ai-bridge/tests/test_webhook_image_caption.py \
  qq-ai-bridge/tests/test_vision_service.py
```

- [ ] **Step 4: Run `git diff --check` and inspect the final diff.** Confirm no key appears in tracked files, no generated files were edited, and only the requested feature/config files changed.

- [ ] **Step 5: Commit the implementation if `.git` is writable.**

```bash
git add qq-ai-bridge/vision/client.py qq-ai-bridge/apps/qq_ai_bridge/services/draw_service.py qq-ai-bridge/apps/qq_ai_bridge/skills/draw.py qq-ai-bridge/apps/qq_ai_bridge/skills/registry.py qq-ai-bridge/apps/qq_ai_bridge/adapters/napcat_client.py qq-ai-bridge/tests/test_vision_client.py qq-ai-bridge/tests/test_draw_service.py qq-ai-bridge/tests/test_draw_skill.py qq-ai-bridge/tests/test_napcat_client.py qq-ai-bridge/.env.example qq-ai-bridge/apps/qq_ai_bridge/config/settings.py qq-ai-bridge/tests/test_kimi_config_defaults.py
git commit -m "feat: add Gemini vision and draw command"
```
