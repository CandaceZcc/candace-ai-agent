# Fixed-Slot Email Digest Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every evaluated digest slot, including empty slots, so digest-level mail waits for the next configured 12:30 or 20:30 delivery time.

**Architecture:** Keep the existing 24-hour catch-up calculation and durable slot-token schema. Change only `EmailAutomationService.run_digest`: when a due slot has no selected records, persist that slot through the existing `mark_digest_sent((), slot_token, now)` operation without calling QQ. Non-empty delivery and failed-send retry behavior remain unchanged.

**Tech Stack:** Python 3.12, standard-library `unittest`, JSON atomic state, existing email automation service and runner, NapCat audit log

---

### Task 1: Add The Empty-Slot Regression Test

**Files:**
- Modify: `qq-ai-bridge/tests/test_email_automation_service.py`

- [ ] **Step 1: Replace the existing empty-digest test with the required behavior**

```python
async def test_empty_digest_closes_slot_without_sending(self):
    service = self.service()

    await service.run_digest(NOW, "12:30")

    self.assertEqual(self.sent, [])
    self.assertTrue(
        self.store.was_digest_slot_sent("email_digest:2026-07-21:12:30")
    )

    await service.run_digest(NOW, "12:30")

    self.assertEqual(self.sent, [])
```

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest \
  qq-ai-bridge/tests/test_email_automation_service.py -v
```

Expected: exactly one failure at `test_empty_digest_closes_slot_without_sending`, because `was_digest_slot_sent(...)` returns `False`; all neighboring tests pass.

### Task 2: Close Empty Digest Slots

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/email_automation_service.py`
- Test: `qq-ai-bridge/tests/test_email_automation_service.py`

- [ ] **Step 1: Add the minimal empty-selection persistence**

Change the empty-selection branch in `EmailAutomationService.run_digest` to:

```python
selected = _select_digest_records(self._store.pending_digest(now, lookback_hours=24))
if not selected:
    self._store.mark_digest_sent((), slot_token, now)
    return
```

- [ ] **Step 2: Run the focused test and verify GREEN**

Run:

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest \
  qq-ai-bridge/tests/test_email_automation_service.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Run adjacent scheduling and persistence tests**

Run:

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest \
  qq-ai-bridge/tests/test_email_automation_service.py \
  qq-ai-bridge/tests/test_email_automation_runner.py \
  qq-ai-bridge/tests/test_email_processing_store.py -v
```

Expected: all tests pass, including failed-send retries and 24-hour restart catch-up.

- [ ] **Step 4: Commit the regression fix**

```bash
git add \
  qq-ai-bridge/apps/qq_ai_bridge/services/email_automation_service.py \
  qq-ai-bridge/tests/test_email_automation_service.py
git commit -m "fix: close empty email digest slots"
```

### Task 3: Verify The Branch

**Files:**
- Verify only

- [ ] **Step 1: Run the complete Bridge test suite**

```bash
PYTHONPATH=qq-ai-bridge .venv/bin/python -m unittest discover \
  -s qq-ai-bridge/tests -p 'test_*.py'
```

Expected: zero failures and zero errors.

- [ ] **Step 2: Run focused static and compile checks**

```bash
.venv/bin/ruff check \
  qq-ai-bridge/apps/qq_ai_bridge/services/email_automation_service.py \
  qq-ai-bridge/tests/test_email_automation_service.py
PYTHONPATH=qq-ai-bridge .venv/bin/python -m compileall -q \
  qq-ai-bridge/apps/qq_ai_bridge qq-ai-bridge/shared qq-ai-bridge/scripts
git diff --check
```

Expected: all commands exit zero.

- [ ] **Step 3: Verify current-tree secret hygiene**

```bash
test -z "$(git ls-files -- zcc zcc.pub)"
! git grep -q -E \
  'sk-[0-9A-Fa-f]{48,}|-----BEGIN (OPENSSH|RSA|EC|DSA) PRIVATE KEY-----' -- .
```

Expected: the local key remains ignored and no tracked long hexadecimal API key or private-key block is present.

### Task 4: Deploy And Verify Production Timing

**Files:**
- Runtime only: `.runtime/pids/email-bridge.pid`
- Runtime only: `/home/cancade/candace-ai-agent/qq-ai-bridge/data/email/automation-state.json`
- Runtime only: `/home/cancade/candace-ai-agent/qq-ai-bridge/data/logs/napcat_outbound.jsonl`

- [ ] **Step 1: Capture the pre-restart state without message content**

Record the verified Bridge PID, current outbound-audit line count, UID `4743` delivery state, and current digest-slot keys. Do not print sender, subject, body, model summary, credentials, or QQ identity.

- [ ] **Step 2: Safely restart the verified feature-worktree Bridge**

Validate that the PID from `.runtime/pids/email-bridge.pid` belongs to this worktree and runs `qq-ai-bridge/bridge.py`. Send SIGTERM, require exit, then start with `/home/cancade/.candace/qq-ai-bridge.env`, write the new PID, and require two consecutive HTTP 200 checks from `http://127.0.0.1:5000/admin/groups`.

- [ ] **Step 3: Verify the corrected slot state**

Wait for the startup runner pass, then require:

```text
email_digest:2026-07-22:12:30 is present
UID 4743 remains digest_sent
outbound audit count has not increased
```

- [ ] **Step 4: Verify one complete production poll is idempotent**

Wait at least 310 seconds. Require the cursor to remain `4743`, both acceptance records to retain their terminal states, and the outbound audit count to remain unchanged. Confirm the latest Bridge log has no email startup, poll, digest, or service-setup failure.

- [ ] **Step 5: Re-run redacted live diagnostics**

```bash
set -a
source /home/cancade/.candace/qq-ai-bridge.env
set +a
PYTHONPATH=qq-ai-bridge .venv/bin/python qq-ai-bridge/scripts/email_agent_check.py --config
PYTHONPATH=qq-ai-bridge .venv/bin/python qq-ai-bridge/scripts/email_agent_check.py --imap
PYTHONPATH=qq-ai-bridge .venv/bin/python qq-ai-bridge/scripts/email_agent_check.py --shadow-report
```

Expected: redacted configuration is valid, read-only IMAP succeeds, and no messages remain pending analysis or digest.

- [ ] **Step 6: Update this plan, commit the rollout record, and push the retained branch**

Mark completed checkboxes, commit only this plan, push `feat/phase-a-qq-email-digest`, and verify `HEAD...@{upstream}` reports `0 0`. Leave the user's untracked Chinese specification untouched.
