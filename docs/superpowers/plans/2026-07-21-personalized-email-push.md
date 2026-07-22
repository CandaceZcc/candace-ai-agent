# Personalized Campus Email Push Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read-only five-minute email monitoring, personalized rule-plus-model triage, urgent QQ alerts, twice-daily incremental digests, and reversible feedback learning without exposing private email data.

**Architecture:** Extend the existing safe IMAP and tool-free email summary foundation with focused services for preferences, deterministic rules, processing state, UID polling, semantic classification, and delivery coordination. Run automation in its own bounded background worker so model or IMAP latency cannot delay existing reminders; keep every automation and delivery switch default-off.

**Tech Stack:** Python 3.10+ standard library, `imaplib`, JSON atomic stores, OpenAI Agents SDK runtime through the existing QuotaRouter provider, NapCat, `unittest`, `unittest.mock`, Ruff

---

## Locked Safety Decisions

- Work only in `feat/phase-a-qq-email-digest` under the existing isolated worktree.
- Preserve the unrelated untracked Chinese spec file; never stage it.
- Never add real credentials, email bodies, sender addresses, runtime logs, or learned preferences.
- Keep IMAP read-only and do not add SMTP or mutation methods.
- Keep `EMAIL_MONITOR_ENABLED`, `EMAIL_IMMEDIATE_PUSH_ENABLED`, and `EMAIL_DIGEST_PUSH_ENABLED` false in live configuration until staged approval.
- Email model runs use `tools=[]`, no fallback, and bounded untrusted content.
- Email QQ sends use redacted outbound auditing before any automation can be enabled.
- Do not infer teacher-versus-institution identity from domain or display name; school
  and teacher mail share the same education domain. Use thread, subject, recipient,
  action, and semantic signals unless the owner explicitly configures a sender rule.

### Task 1: Add Automation Configuration and Domain Contracts

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/config/settings.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/email_models.py`
- Modify: `qq-ai-bridge/.env.example`
- Modify: `qq-ai-bridge/tests/test_email_config.py`
- Create: `qq-ai-bridge/tests/test_email_automation_models.py`

- [x] **Step 1: Write failing configuration tests**

Add tests that assert default-off automation, a 300-second bounded poll interval,
parsed digest times `("12:30", "20:30")`, shadow mode on by default, owner validation,
and profile/state paths that reveal no credential value.

```python
def test_email_automation_defaults_are_safe(self):
    settings = reload_settings_with({})
    self.assertFalse(settings.EMAIL_MONITOR_ENABLED)
    self.assertFalse(settings.EMAIL_IMMEDIATE_PUSH_ENABLED)
    self.assertFalse(settings.EMAIL_DIGEST_PUSH_ENABLED)
    self.assertTrue(settings.EMAIL_SHADOW_MODE)
    self.assertEqual(settings.EMAIL_POLL_INTERVAL_SECONDS, 300)
    self.assertEqual(settings.EMAIL_DIGEST_TIMES, ("12:30", "20:30"))
```

- [x] **Step 2: Write failing model-contract tests**

Define tests for immutable `EmailFetchedMessage`, `EmailRuleDecision`, and
`EmailClassification` values. Validate score bounds, urgency literals, alias format,
and nullable deadlines.

```python
classification = EmailClassification(
    alias="E-1042",
    relevance_score=92,
    urgency="high",
    category="course_change",
    concise_title="课程考试安排调整",
    summary="考试时间发生变化。",
    action="今晚前确认。",
    deadline=None,
    reason="与你当前年级课程相关",
    confidence=0.94,
)
self.assertEqual(classification.relevance_score, 92)
```

- [x] **Step 3: Run tests and confirm the missing contracts fail**

Run:

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_config.py \
  qq-ai-bridge/tests/test_email_automation_models.py -v
```

Expected: failures for undefined automation settings and model classes.

- [x] **Step 4: Implement settings and contracts**

Replace the unshipped daily/weekly schedule settings with:

```python
EMAIL_MONITOR_ENABLED = _get_bool_env("EMAIL_MONITOR_ENABLED", False)
EMAIL_IMMEDIATE_PUSH_ENABLED = _get_bool_env("EMAIL_IMMEDIATE_PUSH_ENABLED", False)
EMAIL_DIGEST_PUSH_ENABLED = _get_bool_env("EMAIL_DIGEST_PUSH_ENABLED", False)
EMAIL_SHADOW_MODE = _get_bool_env("EMAIL_SHADOW_MODE", True)
EMAIL_POLL_INTERVAL_SECONDS = min(
    3600, max(60, _get_int_env("EMAIL_POLL_INTERVAL_SECONDS", 300))
)
EMAIL_DIGEST_TIMES = _parse_email_digest_times(
    os.getenv("EMAIL_DIGEST_TIMES", "12:30,20:30")
)
EMAIL_PROFILE_PATH = os.path.expanduser(
    os.getenv("EMAIL_PROFILE_PATH", "~/.candace/email-agent/profile.json")
)
EMAIL_FEEDBACK_PATH = os.path.expanduser(
    os.getenv("EMAIL_FEEDBACK_PATH", "~/.candace/email-agent/learned-feedback.json")
)
EMAIL_AUTOMATION_STATE_PATH = os.path.join(BASE_DATA_DIR, "email", "automation-state.json")
```

Add frozen dataclasses and literal types to `email_models.py`. Reject out-of-range
scores/confidence and invalid urgency values in `__post_init__`.

- [x] **Step 5: Update the environment template without values**

Document the new default-off flags and remove the unshipped daily/weekly entries.
Keep username, password, and API key assignments empty.

- [x] **Step 6: Run focused tests**

Expected: all Task 1 tests pass.

- [x] **Step 7: Commit Task 1**

```bash
git add qq-ai-bridge/apps/qq_ai_bridge/config/settings.py \
  qq-ai-bridge/apps/qq_ai_bridge/services/email_models.py \
  qq-ai-bridge/.env.example \
  qq-ai-bridge/tests/test_email_config.py \
  qq-ai-bridge/tests/test_email_automation_models.py
git commit -m "feat: define personalized email automation contracts"
```

### Task 2: Add Private Preference Storage

**Files:**
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_preference_service.py`
- Create: `qq-ai-bridge/tests/test_email_preference_service.py`

- [x] **Step 1: Write failing store tests**

Cover default profile creation, mode `0600`, manual-over-learned precedence,
invalid-file fallback to the last valid profile, bounded feedback weights, reversible
feedback, and no sender/body values in log output.

```python
profile = store.load()
self.assertIn("robotics", profile.interest_terms)
self.assertEqual(stat.S_IMODE(profile_path.stat().st_mode), 0o600)
```

- [x] **Step 2: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_preference_service.py -v
```

Expected: module import failure.

- [x] **Step 3: Implement the profile and learned-feedback stores**

Define immutable `EmailPreferenceProfile` with watched/ignored senders and domains,
positive/negative terms, interest aliases, score adjustments, hard-ignore rules, and
`profile_version`. Use standard-library JSON, atomic replacement, and
`os.open(temp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)`. Keep a
last-valid in-memory profile and expose these exact public contracts:

```python
class EmailPreferenceStore:
    def load(self) -> EmailPreferenceProfile:
        """Return the last valid manual-plus-learned profile."""

    def summary(self) -> str:
        """Return a credential-safe preference summary."""

    def apply_feedback(self, alias: str, action: str, signals: dict[str, str]) -> None:
        """Persist one bounded, reversible owner feedback record."""

    def undo_feedback(self, alias: str) -> bool:
        """Remove feedback for an alias and report whether it existed."""
```

Seed the approved CS, AI, software, data, security, systems, algorithms, robotics,
embedded, IoT, Year 3, and 2024-cohort terms. Do not seed real addresses or domains.

- [x] **Step 4: Run tests and commit**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_preference_service.py -v
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_preference_service.py \
  qq-ai-bridge/tests/test_email_preference_service.py
git commit -m "feat: add private email preference learning"
```

### Task 3: Add Explainable Rule Classification

**Files:**
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_rule_classifier.py`
- Create: `qq-ai-bridge/tests/test_email_rule_classifier.py`

- [x] **Step 1: Write the rule matrix as failing tests**

Cover direct `Re:` replies, direct-recipient evidence, cohort and interest terms,
course/exam actions, research and competition terms, generic recruiting penalties,
routine-event penalties, explicit hard ignores, and positive-signal overrides.

```python
decision = classifier.classify(envelope(subject="Re: course exam change"), profile)
self.assertEqual(decision.eligibility, "semantic_required")
self.assertIn("direct_reply", decision.positive_signals)
self.assertGreaterEqual(decision.initial_score, 60)
```

- [x] **Step 2: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_rule_classifier.py -v
```

- [x] **Step 3: Implement deterministic, bounded scoring**

Normalize case and whitespace, inspect sender display/address, recipients, subject,
and a bounded body prefix. Return `EmailRuleDecision` with `initial_score`,
`eligibility`, positive signals, and negative signals. Only explicit owner hard-ignore
rules can return `explicit_hard_ignore`; generic low-value requires strong negative
evidence and no positive evidence. Recipient breadth or a bulk marker alone remains
`semantic_required`; it becomes deterministic low-value only with a strong content
signal such as generic recruiting or a routine activity notice.

- [x] **Step 4: Run tests and commit**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_rule_classifier.py -v
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_rule_classifier.py \
  qq-ai-bridge/tests/test_email_rule_classifier.py
git commit -m "feat: classify email relevance with local rules"
```

### Task 4: Add Durable Processing State and Aliases

**Files:**
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_processing_store.py`
- Create: `qq-ai-bridge/tests/test_email_processing_store.py`

- [x] **Step 1: Write failing state tests**

Cover atomic mode-`0600` writes, stable `E-NNNN` aliases, mailbox cursor durability,
`UIDVALIDITY` reset, Message-ID hash deduplication, decision persistence, immediate and
digest terminal states, 24-hour digest queries, feedback lookup, and restart reload.

```python
record = store.observe(uid_validity="44", uid=17, envelope=envelope())
self.assertRegex(record.alias, r"^E-\d{4,}$")
self.assertEqual(store.cursor("INBOX").last_uid, 17)
```

- [x] **Step 2: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_processing_store.py -v
```

- [x] **Step 3: Implement one atomic automation-state document**

Use a schema containing mailbox cursors, next alias number, message records, digest
slot tokens, and deduplicated alert/recovery state. Store only hashes and structured
classification output; raw bodies remain in the existing retention-bound archive.
Expose explicit transitions instead of generic dictionary mutation. The contracts
must use these parameter and return types:

```python
observe(
    mailbox: str,
    uid_validity: str,
    uid: int,
    envelope: EmailEnvelope,
) -> EmailProcessingRecord
save_rule_decision(alias: str, decision: EmailRuleDecision) -> None
save_classification(alias: str, classification: EmailClassification) -> None
mark_immediate_sent(alias: str, sent_at: datetime) -> None
pending_digest(
    now: datetime,
    lookback_hours: int = 24,
) -> tuple[EmailProcessingRecord, ...]
mark_digest_sent(
    aliases: tuple[str, ...],
    slot_token: str,
    sent_at: datetime,
) -> None
find_by_alias(alias: str) -> EmailProcessingRecord | None
```

- [x] **Step 4: Run tests and commit**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_processing_store.py -v
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_processing_store.py \
  qq-ai-bridge/tests/test_email_processing_store.py
git commit -m "feat: persist email automation decisions"
```

### Task 5: Add Tool-free Structured Semantic Classification

**Files:**
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_semantic_classifier.py`
- Modify: `qq-ai-bridge/shared/ai/agent_runtime.py`
- Modify: `qq-ai-bridge/tests/test_agent_runtime.py`
- Create: `qq-ai-bridge/tests/test_email_semantic_classifier.py`

- [x] **Step 1: Write failing classifier tests**

Test bounded batched prompts, untrusted-data escaping, strict alias matching, valid JSON,
fenced JSON normalization, score and urgency validation, null deadlines, malformed
output rejection, and zero tools.

```python
result = await classifier.classify([(alias, envelope, rule_decision)])
request = runtime.run.await_args.args[0]
self.assertEqual(request.route, "email_classification")
self.assertEqual(request.allowed_tool_names, ())
self.assertNotIn("</email_body>", request.user_text)
```

- [x] **Step 2: Extend the runtime's email safety policy**

Treat both `email_summary` and `email_classification` as email-safe routes. Reject any
requested tools and never use legacy fallback for either route.

- [x] **Step 3: Implement structured parsing**

Build a bounded prompt from sanitized metadata/body prefixes and parse a top-level
`{"items": [item_object]}` response into `EmailClassification` values. Require exactly one
result per requested alias and reject invented aliases.

- [x] **Step 4: Run tests and commit**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_semantic_classifier.py \
  qq-ai-bridge/tests/test_agent_runtime.py -v
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_semantic_classifier.py \
  qq-ai-bridge/shared/ai/agent_runtime.py \
  qq-ai-bridge/tests/test_email_semantic_classifier.py \
  qq-ai-bridge/tests/test_agent_runtime.py
git commit -m "feat: classify email with a tool free model"
```

### Task 6: Add Read-only UID Polling

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/email_imap_service.py`
- Modify: `qq-ai-bridge/tests/test_email_imap_service.py`

- [x] **Step 1: Write failing UID tests**

Add fake IMAP `uid()` and `response("UIDVALIDITY")` behavior. Verify search starts after
the durable cursor, fetch uses UID mode, results are ordered oldest-to-newest, batches
are capped, empty searches do not fetch, and no mutation methods are called.

```python
batch = service.fetch_new(last_uid=41, limit=20)
self.assertEqual(batch.uid_validity, "9001")
self.assertEqual([item.uid for item in batch.messages], [42, 43])
```

- [x] **Step 2: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_imap_service.py -v
```

- [x] **Step 3: Implement `fetch_new` without changing range fetch behavior**

Select `readonly=True`, read UIDVALIDITY, execute UID SEARCH and UID FETCH, parse each
message through the existing parser, and return `EmailUidBatch`. Do not expose server
responses in errors.

- [x] **Step 4: Run tests and commit**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_imap_service.py -v
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_imap_service.py \
  qq-ai-bridge/tests/test_email_imap_service.py
git commit -m "feat: poll new email with read only uid queries"
```

### Task 7: Redact Sensitive QQ Outbound Auditing

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/adapters/napcat_client.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/skills/email.py`
- Modify: `qq-ai-bridge/tests/test_napcat_client.py`
- Modify: `qq-ai-bridge/tests/test_email_skill.py`

- [x] **Step 1: Write failing redaction tests**

Add a `redact_content` send option. Assert that a sensitive message reaches the mocked
NapCat request but neither stdout nor `napcat_outbound.jsonl` contains subject, body,
sender, or message text. Audit metadata may include character count and part number.

- [x] **Step 2: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_napcat_client.py \
  qq-ai-bridge/tests/test_email_skill.py -v
```

- [x] **Step 3: Implement and adopt content redaction**

Extend
`send_private_msg(user_id, msg, quiet=False, force_parts=None, reply_to_message_id=None,
redact_content=False)`. When true, suppress console
previews and store `message_preview="[redacted]"` plus `message_chars`; retain safe HTTP
status fields. Pass `redact_content=True` from every manual and automatic email send.

- [x] **Step 4: Run tests and commit**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_napcat_client.py \
  qq-ai-bridge/tests/test_email_skill.py -v
git add qq-ai-bridge/apps/qq_ai_bridge/adapters/napcat_client.py \
  qq-ai-bridge/apps/qq_ai_bridge/skills/email.py \
  qq-ai-bridge/tests/test_napcat_client.py \
  qq-ai-bridge/tests/test_email_skill.py
git commit -m "fix: redact email content from outbound logs"
```

### Task 8: Build the Automation and Delivery Coordinator

**Files:**
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_automation_service.py`
- Create: `qq-ai-bridge/tests/test_email_automation_service.py`

- [x] **Step 1: Write failing end-to-end service tests**

Cover disabled monitor, archive-before-cursor ordering, hard ignore without model use,
batched semantic classification, immediate threshold `>=80` plus high urgency, digest
threshold `>=60`, possible-related threshold, shadow mode, no raw delivery, failed-send
retry, and restart deduplication.

- [x] **Step 2: Write digest tests**

Verify 24-hour incremental selection, no empty digest, limits of 3 action + 4 relevant
+ 1 possible items, priority sorting, compressed titles, sender display names, no
already-immediate item, slot idempotency, and mark-after-success behavior.

- [x] **Step 3: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_automation_service.py -v
```

- [x] **Step 4: Implement orchestration**

Inject IMAP, archive, preference, rule, semantic, processing, runtime-send, and clock
dependencies. `poll(now)` processes new messages and `run_digest(now, slot)` sends an
incremental digest. Keep deterministic routing in one pure helper and format QQ text
only from `EmailClassification`, never from `EmailEnvelope.body_text`.

- [x] **Step 5: Run tests and commit**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_automation_service.py -v
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_automation_service.py \
  qq-ai-bridge/tests/test_email_automation_service.py
git commit -m "feat: route personalized email alerts and digests"
```

### Task 9: Add Owner Feedback Commands

**Files:**
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/email_models.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/email_query_service.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/skills/email.py`
- Modify: `qq-ai-bridge/tests/test_email_query_service.py`
- Modify: `qq-ai-bridge/tests/test_email_skill.py`

- [x] **Step 1: Write failing parser and authorization tests**

Cover `有用`, `忽略`, `忽略此类`, `关注发件人`, `撤销反馈`, and `邮件 偏好`; reject
malformed aliases, non-owner users, and group contexts.

- [x] **Step 2: Write failing behavior tests**

Resolve aliases through `EmailProcessingStore`, apply reversible feedback through
`EmailPreferenceStore`, show a redacted preference summary, and return a deterministic
not-found message for expired aliases.

- [x] **Step 3: Implement parser and skill paths**

Add `feedback` and `preferences` command kinds. Handle them synchronously before range
queries. Keep all responses owner-private and pass no raw email data into response text.

- [x] **Step 4: Run tests and commit**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_query_service.py \
  qq-ai-bridge/tests/test_email_skill.py -v
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_models.py \
  qq-ai-bridge/apps/qq_ai_bridge/services/email_query_service.py \
  qq-ai-bridge/apps/qq_ai_bridge/skills/email.py \
  qq-ai-bridge/tests/test_email_query_service.py \
  qq-ai-bridge/tests/test_email_skill.py
git commit -m "feat: learn email preferences from qq feedback"
```

### Task 10: Run Automation in an Independent Background Worker

**Files:**
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_automation_runner.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/scheduler.py`
- Create: `qq-ai-bridge/tests/test_email_automation_runner.py`
- Modify: `qq-ai-bridge/tests/test_schedule_service.py`

- [x] **Step 1: Write deterministic runner tests**

Patch clock, sleep, and service factory. Verify immediate first poll, configured poll
interval, due slots at 12:30/20:30, restart catch-up limited to 24 hours, independent
flags, exception isolation, and no effect on existing reminder jobs.

- [x] **Step 2: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_automation_runner.py \
  qq-ai-bridge/tests/test_schedule_service.py -v
```

- [x] **Step 3: Implement the runner**

Start one daemon thread named `email-automation` from `start_scheduler()`. The runner
builds one service instance, polls at the configured interval, checks digest slots, and
catches errors without terminating or blocking `qq-reminder-scheduler`.

- [x] **Step 4: Run tests and commit**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_automation_runner.py \
  qq-ai-bridge/tests/test_schedule_service.py -v
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_automation_runner.py \
  qq-ai-bridge/apps/qq_ai_bridge/services/scheduler.py \
  qq-ai-bridge/tests/test_email_automation_runner.py \
  qq-ai-bridge/tests/test_schedule_service.py
git commit -m "feat: schedule personalized email automation"
```

### Task 11: Add Diagnostics, Documentation, and Final Verification

**Files:**
- Create: `qq-ai-bridge/scripts/email_agent_check.py`
- Create: `qq-ai-bridge/tests/test_email_agent_check.py`
- Create: `docs/install/qq-email-agent.md`
- Modify: `docs/install/run.md`
- Modify: `README.md`
- Modify: `docs/superpowers/plans/2026-07-20-phase-a-execution.md`

- [x] **Step 1: Write failing diagnostic tests**

Cover `--config`, read-only `--imap`, `--shadow-report`, `--cleanup --dry-run`, masked
identity, password `set`/`missing`, no stdin, and no raw content.

- [x] **Step 2: Implement diagnostics and operator documentation**

Document external mode-`0600` secrets/profile files, cloud model privacy, approved QQ
commands, five-minute polling, two digest slots, feedback, shadow mode, retention,
redacted logs, rollout, and rollback. Mark the old Phase A Tasks 7-9 as superseded by
this plan.

- [x] **Step 3: Run the complete focused email suite**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_config.py \
  qq-ai-bridge/tests/test_email_automation_models.py \
  qq-ai-bridge/tests/test_email_parser.py \
  qq-ai-bridge/tests/test_email_imap_service.py \
  qq-ai-bridge/tests/test_email_archive_service.py \
  qq-ai-bridge/tests/test_email_digest_service.py \
  qq-ai-bridge/tests/test_email_preference_service.py \
  qq-ai-bridge/tests/test_email_rule_classifier.py \
  qq-ai-bridge/tests/test_email_processing_store.py \
  qq-ai-bridge/tests/test_email_semantic_classifier.py \
  qq-ai-bridge/tests/test_email_automation_service.py \
  qq-ai-bridge/tests/test_email_automation_runner.py \
  qq-ai-bridge/tests/test_email_query_service.py \
  qq-ai-bridge/tests/test_email_skill.py \
  qq-ai-bridge/tests/test_email_agent_check.py \
  qq-ai-bridge/tests/test_agent_runtime.py \
  qq-ai-bridge/tests/test_schedule_service.py -v
```

Expected: all listed tests pass.

- [x] **Step 4: Run repository verification**

```bash
bash run_ruff.sh
bash run_ruff_2.sh
PYTHONPATH=qq-ai-bridge python -m compileall -q \
  qq-ai-bridge/apps/qq_ai_bridge qq-ai-bridge/shared qq-ai-bridge/scripts
git diff --check
```

- [x] **Step 5: Scan for forbidden content**

```bash
rg -n "smtp|smtplib|input\(" \
  qq-ai-bridge/apps/qq_ai_bridge/services/email_* \
  qq-ai-bridge/apps/qq_ai_bridge/skills/email.py \
  qq-ai-bridge/scripts/email_agent_check.py
git grep -n -E \
  "sk-[A-Za-z0-9_-]{16,}|Authorization: Bearer|EMAIL_IMAP_PASSWORD=.+|OPENAI_API_KEY=.+"
```

Expected: no SMTP, stdin prompt, real secret, or real email content.

- [x] **Step 6: Commit Task 11**

```bash
git add qq-ai-bridge/scripts/email_agent_check.py \
  qq-ai-bridge/tests/test_email_agent_check.py \
  docs/install/qq-email-agent.md docs/install/run.md README.md \
  docs/superpowers/plans/2026-07-20-phase-a-execution.md
git commit -m "docs: add personalized email automation operations"
```

## Live Rollout Gate

Implementation completion does not enable live automation. After code review:

1. Keep immediate and digest delivery false.
2. Enable monitor plus `EMAIL_SHADOW_MODE=true` for 24 hours.
3. Review only the local redacted decision report and adjust profile rules.
4. Obtain explicit approval before setting `EMAIL_IMMEDIATE_PUSH_ENABLED=true`.
5. Obtain explicit approval before setting `EMAIL_DIGEST_PUSH_ENABLED=true`.
6. Verify restart idempotency and provider billing before leaving automation enabled.
