# Fixed-Slot Email Digest Closure Design

**Date:** 2026-07-22
**Status:** Approved
**Scope:** Personalized campus email digest scheduling only

## Problem

The runner checks every configured digest slot from the preceding 24 hours. A slot is
currently persisted only after a non-empty digest is delivered successfully. If a slot
has no eligible mail, it remains open. A digest-level message arriving hours later can
therefore use that old slot and be pushed outside the configured 12:30 and 20:30 times.

The live acceptance run reproduced this behavior: a message processed at 17:03 used the
previous day's 20:30 slot.

## Decision

A due digest slot is closed after it is evaluated, even when no records are selected.
The existing `EmailProcessingStore.mark_digest_sent` operation accepts an empty alias
tuple and already persists the slot token, so no new storage API or schema is needed.

`EmailAutomationService.run_digest` will keep its existing order:

1. Return when digest delivery is disabled or shadow mode is active.
2. Derive the durable slot token and return when that token is already closed.
3. Select eligible records from the preceding 24 hours.
4. When selection is empty, persist the slot with an empty alias tuple and return without
   calling QQ.
5. When selection is non-empty, send the digest and close the slot only after a successful
   QQ response.

## Catch-Up Semantics

The runner keeps its existing 24-hour catch-up window. If the service was offline at a
scheduled slot and eligible records already exist when it restarts, it sends one catch-up
digest. If no records exist at that first evaluation, the slot is closed and mail arriving
later waits for the next configured slot.

This preserves retry behavior: a failed QQ send leaves both the records and slot open for
the next poll.

## Verification

Add a regression assertion showing that an empty digest sends no QQ message but closes the
slot. Re-running the same slot must remain a no-op. Then run the focused automation tests,
the complete bridge suite, Ruff on the touched email files, compile checks, and restart the
production Bridge. After restart, verify that the current empty due slot is persisted and
that another poll produces no duplicate QQ delivery.

## Non-Goals

- Changing the 12:30 and 20:30 schedule.
- Changing immediate-push thresholds or semantic classification.
- Adding SMTP or mailbox mutation.
- Migrating existing processing-state data.
