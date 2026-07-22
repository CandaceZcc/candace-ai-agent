# Email Live Simulation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe synthetic end-to-end rehearsal, prove real model and QQ delivery, and enable production read-only email automation.

**Architecture:** Add a diagnostic-only in-memory IMAP adapter and isolated temporary stores around the existing production automation service. Keep real delivery behind two explicit CLI flags, then activate existing environment switches only after idempotency and privacy checks pass.

**Tech Stack:** Python 3.10+, `argparse`, `tempfile`, existing email automation services, OpenAI Agents SDK runtime, NapCat, `unittest`

---

### Task 1: Add Synthetic Simulation Contracts

**Files:**
- Modify: `qq-ai-bridge/tests/test_email_agent_check.py`
- Modify: `qq-ai-bridge/scripts/email_agent_check.py`

- [x] **Step 1: Write failing tests**

Add tests proving `--simulate-automation` uses isolated synthetic messages,
classifies all scenarios, sends nothing by default, requires both live-delivery
flags, reports only safe fields, and checks repeated poll/digest idempotency:

```python
def test_simulation_requires_explicit_qq_acceptance(self):
    with self.assertRaises(SystemExit):
        self.run_main("--simulate-automation", "--deliver-to-owner")

def test_simulation_routes_three_scenarios_without_live_send(self):
    report = asyncio.run(
        email_agent_check._run_automation_simulation(
            deliver_to_owner=False,
            semantic_classifier=FakeSimulationClassifier(),
            send_private=MagicMock(),
        )
    )
    self.assertTrue(report["ok"])
    self.assertEqual(
        [item["route"] for item in report["scenarios"]],
        ["immediate", "digest", "ignore"],
    )
    self.assertEqual(report["send_counts"], {"digest": 1, "immediate": 1, "total": 2})
    self.assertTrue(report["idempotency"]["digest"])
    self.assertTrue(report["idempotency"]["poll"])
```

- [x] **Step 2: Verify RED**

Run:

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_agent_check.py -v
```

Expected: parser rejects `--simulate-automation`.

- [x] **Step 3: Implement the simulation**

Build the production automation service with an in-memory UID batch, temporary
archive/state/profile paths, production rule and semantic classifiers, and either
an in-memory sender or the production redacted NapCat sender. Run the scenario
twice and emit a bounded JSON report with these contracts:

```python
class _SyntheticImapService:
    def fetch_new(self, *, last_uid: int, limit: int) -> EmailUidBatch:
        """Return only synthetic UIDs newer than the isolated cursor."""


async def _run_automation_simulation(
    *,
    deliver_to_owner: bool,
    semantic_classifier: Any | None = None,
    send_private: Callable[..., Any] = send_private_msg,
) -> dict[str, Any]:
    """Run isolated poll and digest repetitions and return a redacted report."""
```

The CLI branch must require both `--deliver-to-owner` and `--accept-qq-send`,
call `asyncio.run(_run_automation_simulation(...))`, and return exit code 1 when
the report's `ok` field is false.

- [x] **Step 4: Verify GREEN**

Run the focused diagnostic and automation tests and require zero failures.

- [x] **Step 5: Commit**

```bash
git add qq-ai-bridge/scripts/email_agent_check.py \
  qq-ai-bridge/tests/test_email_agent_check.py \
  docs/superpowers/specs/2026-07-22-email-live-simulation-design.md \
  docs/superpowers/plans/2026-07-22-email-live-simulation.md
git commit -m "feat: add safe email automation simulation"
```

### Task 2: Run Real Integration Rehearsal

**Files:**
- No tracked files
- Machine-local runtime state under `/tmp` only

- [x] **Step 1:** Run redacted configuration and read-only IMAP diagnostics.
- [x] **Step 2:** Run the dry synthetic simulation with the real model.
- [x] **Step 3:** Run the live synthetic simulation with explicit QQ consent flags.
- [x] **Step 4:** Confirm exactly one immediate message and one digest, with repeated runs suppressed inside the rehearsal.
- [x] **Step 5:** Inspect only redacted outbound status and ensure no source content appears in logs.

### Task 2.5: Bootstrap The Production Cursor

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/email_models.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/email_imap_service.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/email_processing_store.py`
- Modify: `qq-ai-bridge/scripts/email_agent_check.py`
- Test: `qq-ai-bridge/tests/test_email_automation_models.py`
- Test: `qq-ai-bridge/tests/test_email_imap_service.py`
- Test: `qq-ai-bridge/tests/test_email_processing_store.py`
- Test: `qq-ai-bridge/tests/test_email_agent_check.py`

- [x] **Step 1:** Write failing tests for a structured UID snapshot, read-only `UID SEARCH ALL`, durable baseline setting, explicit CLI acceptance, no backward cursor movement, and redacted output.
- [x] **Step 2:** Verify the tests fail because snapshot and baseline contracts are absent.
- [x] **Step 3:** Implement `EmailUidSnapshot`, `snapshot_cursor()`, `set_cursor()`, and `--bootstrap-cursor --accept-skip-existing`.
- [x] **Step 4:** Run the 52-test focused cursor and simulation suite and require zero failures.
- [x] **Step 5:** Commit the cursor bootstrap implementation.

### Task 3: Activate And Verify Production Automation

**Files:**
- Modify outside Git: `/home/cancade/.candace/qq-ai-bridge.env`

- [x] **Step 1:** Run `--bootstrap-cursor --accept-skip-existing` before changing delivery flags.
- [x] **Step 2:** Set monitor, immediate push, and digest push true; set shadow false.
- [x] **Step 3:** Restart the bridge from the email feature worktree.
- [x] **Step 4:** Verify redacted config, read-only IMAP access, worker health, and one-worker restart behavior.
- [x] **Step 5:** Run the full repository test suite and tracked-secret scan.
- [x] **Step 6:** Record the rollback command and report any residual operational risk.
