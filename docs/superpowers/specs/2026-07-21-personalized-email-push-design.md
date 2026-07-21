# Personalized Campus Email Push Design

**Status:** Approved design
**Date:** 2026-07-21
**Scope:** Owner-private, read-only campus email triage and QQ delivery

## Context

The current Phase A email implementation provides a safe foundation:

- owner-private, deterministic QQ commands for date-range queries;
- read-only IMAP over TLS;
- bounded MIME parsing and private local archives;
- tool-free summaries through `gpt-5.6-terra`;
- QQ delivery through NapCat; and
- independent feature flags for the on-demand email path.

It does not yet provide personalized filtering, per-message relevance decisions,
new-mail monitoring, feedback learning, or automatic high-value delivery. The
unimplemented scheduler plan only covers fixed daily and weekly range digests.
That design is superseded by this specification.

## Goals

1. Detect new mail within approximately five minutes without mutating the mailbox.
2. Suppress clearly irrelevant routine mail.
3. Identify personally relevant and high-value mail using deterministic signals,
   model judgment, and owner feedback.
4. Push urgent, highly relevant mail to the owner through QQ immediately.
5. Send deduplicated incremental digests at 12:30 and 20:30 for relevant but
   non-urgent mail from the preceding 24 hours.
6. Send only concise model-derived summaries, never raw email bodies.
7. Display relevance and urgency for every delivered item.
8. Learn from explicit QQ feedback while remaining manually editable and
   explainable.
9. Keep credentials, private email data, learned preferences, state, and runtime
   logs outside Git.

## Non-goals

- Sending email or providing any SMTP capability.
- Marking messages read, moving them, deleting them, or modifying server state.
- Automatically replying to messages.
- Treating every school announcement as useful.
- Sending generic recruiting, internship, or campus activity mail by default.
- Using the image-generation API in the email pipeline.
- Replacing manual commands such as `邮件 今天` and `邮件 本周`.
- A weekly automatic digest. Manual weekly queries remain available.

## Owner Relevance Profile

The initial profile uses the following positive signals:

- a direct person-to-person reply, regardless of whether it uses a school or external domain;
- a message explicitly addressed to the owner rather than only a broad list;
- computer science, computing, computer department, or CST;
- Year 3, third year, 2024 cohort, 大三, or 2024级;
- AI, machine learning, large language models, software engineering, Web, apps,
  data science, databases, cybersecurity, systems, cloud computing, operating
  systems, algorithms, and programming contests;
- robotics, embedded systems, IoT, automation, and software-hardware projects;
- relevant research, academic competitions, and technical events;
- exams, course changes, deadlines, required confirmations, submissions, fees,
  attendance, and account security.

The initial profile uses the following negative signals:

- generic recruiting, campus recruitment, and internship blasts;
- generic commercial or marketing messages;
- routine campus activity announcements with no personal, year, department, or
  technical relevance; and
- repeated bulk notices already explicitly rejected by the owner.

Recruiting or internship mail can still be relevant when it explicitly matches
the owner's field, year, or technical interests. Mail from the school faculty or
computer department is always eligible for semantic review; the sender domain
alone never causes immediate delivery.

Teacher and institutional mail commonly share the same school domain. Automatic
scoring therefore must not infer a person, teacher, or institution from domain or
display name alone. Reply-thread markers, course/exam/action language, recipient
scope, and semantic content provide the default distinction. Sender and domain
weights apply only after explicit manual configuration or owner feedback.

## Architecture

The automation path consists of seven bounded components:

1. `EmailMonitor` polls read-only IMAP for new UIDs.
2. `EmailProcessingStore` persists cursors and per-message state.
3. `EmailPreferenceStore` loads manual rules and learned feedback.
4. `EmailRuleClassifier` applies explainable positive and negative signals.
5. `EmailSemanticClassifier` asks the tool-free model for a structured decision.
6. `EmailDeliveryPlanner` routes each decision to immediate delivery, a digest
   queue, or silent ignore.
7. `EmailFeedbackService` resolves QQ aliases and updates learned preferences.

The existing MIME parser, archive service, Agent runtime, NapCat client, and QQ
skill router remain the implementation foundation.

### Processing Flow

```text
5-minute tick
  -> read-only UID search
  -> persist newly observed identity
  -> bounded MIME parse and archive
  -> deterministic rule score
  -> explicit hard-ignore check
  -> tool-free semantic classification for eligible candidates
  -> persist structured decision
  -> immediate QQ push OR pending digest OR silent ignore
  -> mark delivered only after NapCat success
```

All school-department mail, direct replies, and ambiguous mail with a positive
personal signal reach semantic classification. Model calls may be skipped only
for an explicit owner hard-ignore or a deterministic low-value pattern with no
positive signal.

## Read-only New-mail Monitoring

The monitor runs every 300 seconds by default. It uses IMAP UID commands and
persists:

- mailbox name;
- `UIDVALIDITY`;
- last durably observed UID; and
- a hash of Message-ID for cross-session deduplication.

The cursor advances only after the corresponding processing record has been
written atomically. A poll can process multiple bounded batches when more mail
arrives than the per-run limit.

If `UIDVALIDITY` changes, the monitor establishes a new UID cursor and uses the
Message-ID hash plus the recent processing store to avoid duplicate delivery.
IMAP remains selected with `readonly=True`; no `STORE`, `COPY`, `MOVE`, `EXPUNGE`,
or SMTP operation is permitted.

## Preference Storage and Learning

Private preference data is stored under:

```text
~/.candace/email-agent/profile.json
~/.candace/email-agent/learned-feedback.json
```

Files use atomic replacement and mode `0600`. They are outside the repository.
The manually edited profile has precedence over learned feedback. Invalid manual
configuration does not replace the last valid in-memory profile; the owner
receives one deduplicated QQ configuration alert.

The profile supports:

- watched and ignored senders;
- watched and ignored domains;
- positive and negative phrases;
- interest categories and aliases;
- year and cohort aliases;
- hard-ignore rules created only by explicit owner action;
- score adjustments; and
- a monotonically increasing profile version.

Positive and negative feedback adjusts bounded weights for sender, domain,
category, and extracted semantic signals. Lack of QQ feedback is never treated
as negative feedback. Learned rules remain inspectable and reversible.

When the profile version changes, the system may re-evaluate ignored messages
from the last seven days while respecting the 30-day archive retention boundary.
Re-evaluation cannot duplicate already delivered mail.

## Deterministic Rule Classification

The rule classifier emits an initial score, matched signals, and one of three
eligibility results:

- `semantic_required`;
- `explicit_hard_ignore`; or
- `deterministic_low_value`.

Direct personal replies, direct recipient evidence, owner cohort terms, course
action terms, and technical interest matches raise the score. Generic mass-mail
markers, broad event notices, and generic recruiting lower it. Negative generic
signals never override a direct personal action, exam change, security event, or
explicit positive owner rule.

Only an explicit owner hard-ignore bypasses all semantic analysis. A
deterministic low-value decision requires both strong negative evidence and no
positive owner signal.

A broad recipient, mailing-list marker, or bulk header is only weak evidence.
Bulk school mail still reaches semantic classification unless its subject or
content also carries a strong low-value signal such as generic recruiting or a
routine activity notice.

## Model Classification

Eligible candidates are classified in bounded batches by `gpt-5.6-terra` with
`reasoning_effort=high`. The request uses the existing `email_summary`-grade
security boundary:

- `tools=[]`;
- no hosted search;
- no local tools;
- no legacy chat fallback;
- bounded sanitized content; and
- explicit prompt-injection isolation.

The model returns a strict structured result for each local message alias:

```json
{
  "alias": "E-1042",
  "relevance_score": 92,
  "urgency": "high",
  "category": "course_change",
  "concise_title": "课程考试安排调整",
  "summary": "考试时间和教室发生变化。",
  "action": "今晚前确认新安排。",
  "deadline": "2026-07-22T20:00:00+08:00",
  "reason": "与你当前年级课程直接相关",
  "confidence": 0.94
}
```

Allowed urgency values are `low`, `medium`, `high`, and `critical`. Unknown
deadlines are represented as `null`; the model must not invent a deadline. The
concise title is model-generated unless the original subject is already short
and precise.

Invalid, incomplete, or tool-using output is rejected. It is not converted into
a raw or partially trusted QQ message.

## Routing Policy

The default routing matrix is:

| Relevance | Additional condition | Route |
| --- | --- | --- |
| 80-100 | urgency is high or critical | Immediate QQ push |
| 60-100 | not immediately urgent | Next incremental digest |
| 40-59 | strong personal or technical signal | Possible-relevance digest slot |
| 40-59 | no strong positive signal | Silent ignore, retained for feedback review |
| 0-39 | any non-override condition | Silent ignore |

A deadline within 48 hours, direct required response, exam or course change,
account security event, or likely financial/academic loss can raise urgency.
Relevance and urgency remain separate so a generally important campus notice
does not become an immediate personal interruption.

## QQ Delivery Format

Immediate messages contain no raw body or long original subject:

```text
[相关度 92 | 紧急性 高]
课程考试安排调整

核心：考试时间和教室发生变化。
行动：请在今晚前确认新安排。
截止：7月22日 20:00
来源：发件人名称
编号：E-1042
```

The source preserves the sender display name. The model condenses long subjects;
an already concise subject may be retained. Signatures, quoted replies, tracking
content, long links, and original bodies are never sent to QQ.

## Incremental Digests

Digest jobs run at 12:30 and 20:30 in the configured local timezone. Each job
queries the preceding 24 hours but includes only relevant messages that have not
already been delivered by an immediate push or a successful earlier digest.

Each digest contains at most:

- three `需要行动` items;
- four `值得关注` items; and
- one `可能相关` item.

No empty digest is sent. Similar low-value notices are grouped or omitted. A
short aggregate statement may report that routine notices were ignored, but it
must not enumerate or reproduce them.

The scheduled digest is assembled from persisted short classifications. A
second model call is used only when cross-message grouping is needed. This keeps
API use bounded and prevents repeated transmission of the same body.

## Delivery Idempotency

Each processing record has independent states for analysis, immediate delivery,
digest eligibility, digest delivery, and feedback. Terminal delivery states are
written only after NapCat reports HTTP success and `retcode=0`.

Immediate and digest delivery use idempotency tokens derived from the message
identity and route. A digest run additionally uses a slot token such as:

```text
email_digest:2026-07-21T12:30+08:00
email_digest:2026-07-21T20:30+08:00
```

Failed sends remain pending and retry with bounded backoff. Restart, overlapping
polls, and scheduler catch-up cannot create duplicate QQ messages. Catch-up for
scheduled digests is limited to still-undelivered relevant mail in the preceding
24 hours.

## Feedback Commands

The owner-private `EmailSkill` adds:

```text
邮件 E-1042 有用
邮件 E-1042 忽略
邮件 E-1042 忽略此类
邮件 E-1042 关注发件人
邮件 E-1042 撤销反馈
邮件 偏好
```

Aliases are local identifiers and do not expose IMAP UID or Message-ID. Feedback
commands are rejected for non-owner and group contexts.

`忽略此类` creates a previewable, reversible learned rule. It does not silently
create an unbounded hard blacklist. `邮件 偏好` shows a concise, credential-safe
summary of manual and learned rules. Manual file edits are reloaded without a
bridge restart after validation.

## API Plan

- QuotaRouter `gpt-5.6-terra` with high reasoning handles semantic email
  classification and any necessary cross-message condensation.
- New candidates are batched per poll, and one structured result is reused for
  routing and QQ text.
- DeepSeek V4 remains the ordinary-chat provider and does not receive email by
  default.
- Banana remains image-only and is not reachable from the email path.
- Provider keys and IMAP credentials remain only in the external mode-`0600`
  environment file.

The system records aggregate token use, latency, status, route, and tool-call
counts without content. Per-run limits cap messages and total sanitized
characters before a model request.

## Configuration and Rollback

The revised automation uses independent defaults-off switches:

```dotenv
EMAIL_AGENT_ENABLED=false
EMAIL_MONITOR_ENABLED=false
EMAIL_IMMEDIATE_PUSH_ENABLED=false
EMAIL_DIGEST_PUSH_ENABLED=false
EMAIL_SHADOW_MODE=true
EMAIL_POLL_INTERVAL_SECONDS=300
EMAIL_DIGEST_TIMES=12:30,20:30
```

`EMAIL_AGENT_ENABLED` continues to gate manual owner commands. The three new
automation switches independently gate monitoring, immediate delivery, and
scheduled digest delivery. Shadow mode permits polling and classification but
forbids content delivery.

The unshipped `EMAIL_DAILY_DIGEST_*` and `EMAIL_WEEKLY_DIGEST_*` design is
superseded. Manual daily and weekly query commands remain unchanged.

## Privacy and Logging

All private runtime files live outside Git or under existing ignored data roots.
No real message, sender, address, credential, learned preference, state file,
trace, or attachment may be committed.

Before automation is enabled, current NapCat outbound logging must stop recording
message previews for email deliveries. Email logs may contain only:

- local alias or irreversible hash;
- rule and model scores;
- category and route;
- processing duration and aggregate token counts;
- tool-call counts; and
- redacted delivery status.

The cloud model necessarily processes bounded candidate content. Operator
documentation must state this clearly. Raw sanitized archives retain their
existing 30-day default and are removed by bounded cleanup. Attachments are not
uploaded or summarized in this phase.

## Error Handling

- **Model unavailable:** keep candidates pending and retry; never send raw text.
- **Possible urgent mail while model is unavailable:** send one deduplicated
  content-free operational alert and continue retries.
- **Invalid model result:** reject, record a safe failure code, and retry within
  bounded policy.
- **IMAP failure:** retain the cursor and send one deduplicated operational alert
  after a sustained failure threshold; send one recovery notice.
- **NapCat failure:** do not mark delivery complete; retry without duplicating
  already successful parts.
- **Invalid profile:** keep the last valid profile and notify the owner once.
- **Queue pressure:** process newest urgent candidates first while preserving
  durable state for later bounded batches.

## Verification Strategy

Focused tests must cover:

- UID polling, cursor durability, UIDVALIDITY changes, and read-only enforcement;
- rule precedence, hard-ignore restrictions, and positive-signal overrides;
- structured model parsing, malformed output, and zero-tool enforcement;
- every routing threshold and deadline boundary;
- immediate-send success, partial failure, retry, and restart idempotency;
- 12:30 and 20:30 incremental windows and the eight-item cap;
- suppression of empty and duplicate digests;
- feedback authorization, learning, reversal, and manual-profile precedence;
- invalid profile reload behavior;
- no raw content in QQ, logs, traces, metrics, or tracked files;
- provider outage, IMAP outage, NapCat outage, and recovery; and
- independent rollback switches.

Repository-wide tests, Ruff, compile checks, diff checks, and tracked-secret scans
remain required before a live canary.

## Staged Rollout

1. Implement and verify with all automation switches disabled.
2. Enable monitoring in shadow mode for 24 hours. Produce only a local redacted
   decision report.
3. Review false positives and false negatives, then adjust the initial profile.
4. Enable immediate push while scheduled digests remain disabled.
5. Enable the 12:30 and 20:30 incremental digests.
6. Verify restart idempotency and compare observed API usage with provider billing.
7. Retain the ability to disable monitoring, immediate push, or digest push
   independently without affecting ordinary QQ chat.

## Acceptance Criteria

- New mail is normally evaluated within five minutes.
- High-relevance urgent mail is delivered once through QQ.
- Relevant non-urgent mail appears once in the next eligible digest.
- Clearly irrelevant mail produces no QQ item.
- Delivered text contains a relevance score, urgency, concise title, distilled
  content, sender display name, and local feedback alias, but no raw body.
- Feedback changes future decisions and can be reversed or manually overridden.
- Restart and repeated polling do not duplicate delivery.
- Model runs expose zero tools and no legacy fallback.
- IMAP remains read-only and no SMTP or mutation capability exists.
- Logs and Git contain no credentials, sender addresses, real email content, or
  learned private preferences.
