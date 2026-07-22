# Email Live Simulation Design

**Date:** 2026-07-22
**Scope:** End-to-end rehearsal and activation of personalized campus email delivery

## Goal

Prove the production classification and QQ delivery path without waiting for new
mail, then enable the existing read-only IMAP automation with a reversible rollout.

## Chosen Approach

Extend `email_agent_check.py` with an explicit synthetic automation check. The
check injects deterministic `EmailEnvelope` objects through an in-memory IMAP
adapter while reusing the production rule classifier, semantic classifier,
automation coordinator, QuotaRouter runtime, and NapCat sender.

The simulation uses a temporary archive and processing store, so it never reads,
writes, or advances the real IMAP cursor. It creates three scenarios:

1. an urgent Year 3 course/exam change that must be sent immediately;
2. a robotics competition notice that must appear in the digest; and
3. a generic unrelated recruitment notice that must be ignored.

## Command Contract

```bash
email_agent_check.py --simulate-automation
email_agent_check.py --simulate-automation --deliver-to-owner --accept-qq-send
```

Without both delivery flags, the check uses an in-memory sender and performs no
QQ action. With both flags, it sends only model-distilled messages to the
configured owner through `send_private_msg(..., redact_content=True)`.

The command runs polling twice and each digest slot twice. Its JSON output contains
only scenario names, aliases, route, relevance, urgency, delivery state, send
counts, and boolean idempotency checks. It never prints synthetic source text,
sender addresses, credentials, archive paths, or model prompts.

## Safety And Failure Handling

- Real IMAP is not constructed by the simulation.
- Temporary state is removed when the process exits.
- The model remains tool-free and has no legacy fallback.
- A model, parse, or NapCat failure returns non-zero and leaves no production state.
- QQ delivery requires two explicit command flags.
- Repeated poll and digest calls must not increase successful delivery counts.
- Live environment switches are changed only after the simulation passes.

## Activation

After a successful real-model and real-QQ rehearsal, set monitor, immediate push,
and digest push to true and shadow mode to false in the machine-local mode-`0600`
environment file. Before changing those switches, take a read-only UID snapshot
and persist its highest UID as the production baseline. This intentionally treats
mail already present at activation time as seen and prevents historical mail from
being delivered as new. Restart the bridge from the email feature worktree,
verify the redacted configuration, run one read-only IMAP check, and verify that
the `email-automation` worker survives restart. Rollback restores the three
delivery switches to false and restarts the bridge.

## Acceptance Criteria

- The dry simulation proves expected routing without network delivery.
- The live simulation sends one urgent item and one digest to the owner QQ.
- The unrelated scenario sends nothing.
- Repeated polling and digest execution produce no duplicate QQ messages.
- Simulation does not alter the real automation state or mailbox cursor.
- Cursor bootstrap fetches no message body and never moves a same-mailbox cursor backwards.
- Live configuration enables five-minute monitoring and both digest slots.
- Restart leaves one running email automation worker with no startup error.
