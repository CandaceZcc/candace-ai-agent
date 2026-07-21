# Phase A QQ Agent Modernization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver an owner-private QQ agent that replaces the canary OpenClaw path with OpenAI Agents SDK orchestration, supports verified web search and bounded PC Agent control, and adds on-demand plus scheduled campus-email summaries.

**Architecture:** Execute two dependent plans. First add the in-process Agents SDK provider/runtime/tool layer while preserving NapCat, QQ routing, PC Agent, and a legacy rollback. Then add a read-only IMAP subsystem and deterministic EmailSkill, with summaries delivered only through QQ and scheduled by the existing bridge scheduler.

**Tech Stack:** Python 3.10+, OpenAI Agents SDK 0.18.3, OpenAI Responses or verified third-party Responses proxy, compatible Chat Completions fallback, NapCat, existing PC Agent, IMAP over TLS, `unittest`

> **Superseded email schedule:** The old daily/weekly Milestone 3 and Tasks 7–9 in
> `2026-07-20-qq-email-digest.md` are replaced by
> `2026-07-21-personalized-email-push.md`. The replacement uses five-minute
> read-only monitoring, priority alerts, 12:30/20:30 incremental 24-hour digests,
> and reversible owner feedback. All live automation flags remain default-off.

---

## Locked decisions

- QQ remains the only user terminal in Phase A.
- The Agents SDK replaces neither NapCat nor PC Agent; it replaces the LLM/tool orchestration layer on the owner-private canary path.
- The user's third-party API routes to OpenAI GPT-5.5/5.6 models. Hosted tools are enabled according to the gateway's verified API behavior, not its model label.
- Provider modes are `openai`, `responses_proxy`, and `chat_compatible`.
- Web search requires a real `web_search_call` plus citations from the exact endpoint/model probe.
- Built-in computer use requires a real `computer_call` probe. Actual actions are executed only through the bounded local harness and safety gates.
- ChatGPT Plus is not an SDK credential and does not pay API charges.
- Email access is read-only IMAP. No SMTP, attachment bytes, CodeBuddy subprocess, Windows converter, or interactive prompt is ported.
- Email summaries are tool-free agent runs so untrusted email content cannot invoke browser/computer tools.
- Group chat remains on the existing path during Phase A.

## Documents to read in order

1. Design and provider/account rationale: `docs/superpowers/specs/2026-07-20-phase-a-openai-agents-sdk-email-design.md`
2. Foundation tasks: `docs/superpowers/plans/2026-07-20-openai-agents-sdk-foundation.md`
3. Email tasks: `docs/superpowers/plans/2026-07-20-qq-email-digest.md`

## Milestone 1: Agents SDK foundation

- [ ] Execute every task and focused test in `2026-07-20-openai-agents-sdk-foundation.md`.
- [ ] Verify the configured third-party endpoint with the text Responses probe.
- [ ] Run the billable web-search probe only after accepting its expected charge.
- [ ] Run the computer probe without executing returned actions.
- [ ] Keep hosted capabilities disabled when a probe fails or returns only ordinary text.
- [ ] Enable the new runtime for `OWNER_QQ` private chat only.
- [ ] Confirm normal turns receive no tool schemas.
- [ ] Confirm current-events turns receive only web search.
- [ ] Confirm PC Agent requests receive only the bounded local tool set.
- [ ] Confirm unsafe computer actions stop at approval.
- [ ] Disable the runtime and verify the legacy path still works.

Milestone 1 exits only when provider capability, usage, latency, and rollback are observable and owner-private canary tests pass.

## Milestone 2: On-demand campus email

- [ ] Execute Tasks 1–6 of `2026-07-20-qq-email-digest.md`.
- [ ] Configure an IMAP client-specific password in the external remote environment file.
- [ ] Run configuration and read-only mailbox diagnostics.
- [ ] Confirm the IMAP client selects the mailbox with `readonly=True`.
- [ ] Enable `EMAIL_AGENT_ENABLED` while both schedule flags remain false.
- [ ] Verify `邮件 状态`, `邮件 今天`, `邮件 昨天`, `邮件 本周`, `邮件 上周`, and `邮件 最近 7 天`.
- [ ] Review model usage and local redacted logs after the first live summary.
- [ ] Confirm no full body, credential, or raw MIME message appears in logs/traces.
- [ ] Disable the email feature and verify normal QQ chat is unaffected.

Milestone 2 exits after all commands work, summaries expose zero tools, and the privacy boundary has been accepted.

## Milestone 3: Daily and weekly QQ delivery

This milestone is retained for history and must not be executed. Follow the
superseding personalized email push plan referenced above.

- [ ] Execute Tasks 7–9 of `2026-07-20-qq-email-digest.md`.
- [ ] Enable the daily job first and observe at least three successful daily sends.
- [ ] Restart the bridge after the daily send time and verify no duplicate delivery.
- [ ] Enable the weekly job after the daily canary is stable.
- [ ] Restart within the same ISO week and verify no duplicate weekly delivery.
- [ ] Simulate NapCat failure and confirm no success token is written.
- [ ] Run retention dry-run before allowing actual cleanup.
- [ ] Verify the three independent rollback switches: Agents SDK chat, email commands, and email schedules.

Milestone 3 is superseded; its replacement exits only after the personalized email
push plan passes its shadow canary, restart-idempotency checks, and provider billing
review.

## IDE handoff sequence

From the repository root:

```bash
git switch docs/phase-a-openai-agents-sdk-plan
git status --short --branch
```

Read the design, then execute the foundation plan one task and one commit at a time. Do not start email implementation until the Phase A0 completion gate in the foundation plan passes.

When implementation begins from a different branch, preserve this documentation commit and branch from it:

```bash
git switch -c feat/phase-a-openai-agents-sdk
```

After Milestone 1 is reviewed, create the dependent email branch:

```bash
git switch -c feat/phase-a-qq-email-digest
```

Do not push or deploy from the planning branch. Deployment requires a separate review of the current remote working tree because the inspected remote checkout already contains an unrelated modification in `qq-ai-bridge/config/groups.json`.

## Final acceptance

- [ ] Owner-private QQ no longer needs OpenClaw when the new runtime flag is enabled.
- [ ] Group QQ behavior remains unchanged.
- [ ] Third-party GPT-5.5/5.6 gateway capabilities are proven by response items, not assumed from model naming.
- [ ] Web-search citations are visible as clickable URLs in QQ.
- [ ] Computer actions are local, bounded, observable, and approval-gated.
- [ ] Plus credentials are not used; API/project billing is configured separately.
- [ ] On-demand, daily, and weekly email summaries work through QQ.
- [ ] Email remains read-only and scheduled sends are idempotent.
- [ ] No secret or full email body appears in repository history, logs, or traces.
- [ ] All focused tests, repository lint scripts, and rollback checks pass.
