# QQ Campus Email Digest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Port the useful IMAP, MIME parsing, date-range, archive, and digest behavior from Campus_Exmail_Agent into `candace-ai-agent`, delivering on-demand and scheduled summaries through owner-private QQ without CodeBuddy, interactive CLI prompts, Windows binaries, or SMTP.

**Architecture:** Add a read-only email service layer behind a deterministic owner-only `EmailSkill`, before the fallback `ChatSkill`. Fetch and normalize email through IMAP, cache sanitized records under the existing ignored data directory, summarize through the bounded Agents SDK runtime with no tools, and extend the existing scheduler with daily/weekly idempotent jobs that send through NapCat.

**Tech Stack:** Python 3.10+ standard-library `imaplib`/`email`/`html.parser`, OpenAI Agents SDK foundation from the preceding plan, existing QQ skill router and scheduler, JSON atomic storage, `unittest`, `unittest.mock`

---

## Prerequisites and scope

- Complete `docs/superpowers/plans/2026-07-20-openai-agents-sdk-foundation.md` through its Phase A0 completion gate.
- Use Campus_Exmail_Agent commit `2bd141a` as a behavior reference only.
- The mailbox operation is read-only. Do not set flags, move/delete messages, reply, or send mail.
- No SMTP code enters this repository in Phase A.
- No attachment bytes are downloaded. Record safe attachment metadata only.
- No `input()` or other interactive prompt may exist in a webhook, scheduler, or smoke-test execution path.
- Do not copy `html-to-markdown/html2markdown.exe` or the CodeBuddy subprocess wrapper.
- Real IMAP and API credentials remain in `~/.candace/qq-ai-bridge.env` on the remote host.

## Task 1: Define email configuration, query models, and deterministic date parsing

**Files:**

- Modify: `qq-ai-bridge/.env.example`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/config/settings.py`
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_models.py`
- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_query_service.py`
- Create: `qq-ai-bridge/tests/test_email_config.py`
- Create: `qq-ai-bridge/tests/test_email_query_service.py`

- [ ] **Step 1: Write failing configuration tests**

Follow the repository's existing isolated environment reload pattern. Cover:

```python
class EmailConfigTests(unittest.TestCase):
    def test_email_agent_is_disabled_by_default(self): ...
    def test_default_imap_endpoint_is_tls_port_993(self): ...
    def test_enabled_agent_requires_username_and_password(self): ...
    def test_scheduled_digest_requires_owner_qq(self): ...
    def test_invalid_daily_time_disables_email_schedule_only(self): ...
    def test_invalid_weekday_is_rejected(self): ...
    def test_limits_have_safe_caps(self): ...
    def test_config_summary_redacts_email_and_password(self): ...
```

- [ ] **Step 2: Write failing date-query tests**

Use a fixed Asia/Shanghai date. The parser accepts only the intended commands:

```python
class EmailQueryServiceTests(unittest.TestCase):
    def test_today_range(self): ...
    def test_yesterday_range(self): ...
    def test_this_week_starts_monday(self): ...
    def test_last_week_is_complete_monday_to_sunday(self): ...
    def test_recent_n_days_is_inclusive(self): ...
    def test_recent_days_rejects_zero_and_over_limit(self): ...
    def test_plain_chat_mentioning_email_does_not_match(self): ...
    def test_status_help_and_unknown_subcommand_are_distinct(self): ...
```

Required command grammar:

```text
邮件 今天
邮件 昨天
邮件 本周
邮件 上周
邮件 最近 <1..EMAIL_MAX_RANGE_DAYS> 天
邮件 状态
邮件 帮助
```

- [ ] **Step 3: Run and confirm failures**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_config.py qq-ai-bridge/tests/test_email_query_service.py -v
```

- [ ] **Step 4: Add safe example settings**

Add to `qq-ai-bridge/.env.example`:

```dotenv
# Campus email digest (read-only IMAP, QQ output only)
EMAIL_AGENT_ENABLED=false
EMAIL_IMAP_HOST=imap.exmail.qq.com
EMAIL_IMAP_PORT=993
EMAIL_IMAP_USERNAME=
EMAIL_IMAP_PASSWORD=
EMAIL_IMAP_MAILBOX=INBOX
EMAIL_DAILY_DIGEST_ENABLED=false
EMAIL_DAILY_DIGEST_TIME=20:30
EMAIL_WEEKLY_DIGEST_ENABLED=false
EMAIL_WEEKLY_DIGEST_DAY=sun
EMAIL_WEEKLY_DIGEST_TIME=21:00
EMAIL_SUMMARY_MODEL=
EMAIL_MAX_RANGE_DAYS=31
EMAIL_MAX_MESSAGES_PER_RUN=100
EMAIL_MAX_BODY_CHARS=20000
EMAIL_MAX_TOTAL_CHARS=200000
EMAIL_ARCHIVE_RETENTION_DAYS=30
EMAIL_IMAP_TIMEOUT_SECONDS=30
```

An empty `EMAIL_SUMMARY_MODEL` inherits the foundation runtime's configured model. This allows the user's current GPT-5.5/5.6 provider to summarize mail without assuming hosted tool support.

- [ ] **Step 5: Implement immutable domain models**

Use value objects equivalent to:

```python
@dataclass(frozen=True)
class EmailQuery:
    start_date: date
    end_date: date
    limit: int
    refresh: bool = False

    def __post_init__(self) -> None:
        if self.end_date < self.start_date:
            raise ValueError("end_date must not precede start_date")


@dataclass(frozen=True)
class EmailAttachment:
    filename: str
    content_type: str
    size_bytes: int


@dataclass(frozen=True)
class EmailEnvelope:
    message_id: str
    subject: str
    sender: str
    recipients: tuple[str, ...]
    sent_at: datetime | None
    body_text: str
    attachments: tuple[EmailAttachment, ...]


@dataclass(frozen=True)
class EmailDigest:
    period_label: str
    message_count: int
    summary_text: str
    source_message_ids: tuple[str, ...]
    from_cache: bool
```

Do not store passwords or IMAP connection objects in these values.

- [ ] **Step 6: Implement the command parser and range builder**

The parser returns a typed command (`query`, `status`, `help`, `invalid`, or `no_match`) and never calls the model. Use the repository's local-time helper for date calculations.

- [ ] **Step 7: Run focused tests**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_config.py qq-ai-bridge/tests/test_email_query_service.py -v
```

- [ ] **Step 8: Commit**

```bash
git add qq-ai-bridge/.env.example qq-ai-bridge/apps/qq_ai_bridge/config/settings.py qq-ai-bridge/apps/qq_ai_bridge/services/email_models.py qq-ai-bridge/apps/qq_ai_bridge/services/email_query_service.py qq-ai-bridge/tests/test_email_config.py qq-ai-bridge/tests/test_email_query_service.py
git commit -m "feat: define qq email digest contracts"
```

## Task 2: Port safe MIME parsing without platform binaries

**Files:**

- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_parser.py`
- Create: `qq-ai-bridge/tests/test_email_parser.py`
- Create: `qq-ai-bridge/tests/fixtures/email/plain.eml`
- Create: `qq-ai-bridge/tests/fixtures/email/html_only.eml`
- Create: `qq-ai-bridge/tests/fixtures/email/multipart_attachment.eml`
- Create: `qq-ai-bridge/tests/fixtures/email/malformed_headers.eml`

- [ ] **Step 1: Create synthetic, non-personal `.eml` fixtures**

Fixtures contain invented addresses and content only. Include:

- encoded UTF-8 subject and sender display name;
- `text/plain` message;
- HTML-only message with script, style, tracking image, and links;
- multipart alternative plus one normal attachment and one inline part;
- malformed date/header encodings that must degrade safely.

- [ ] **Step 2: Write failing parser tests**

```python
class EmailParserTests(unittest.TestCase):
    def test_decodes_encoded_headers(self): ...
    def test_prefers_plain_text_body(self): ...
    def test_converts_html_to_readable_text(self): ...
    def test_drops_script_style_and_tracking_resources(self): ...
    def test_does_not_return_attachment_bytes(self): ...
    def test_sanitizes_attachment_filename(self): ...
    def test_caps_body_characters(self): ...
    def test_malformed_headers_do_not_crash(self): ...
    def test_message_id_fallback_is_deterministic(self): ...
```

- [ ] **Step 3: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_parser.py -v
```

- [ ] **Step 4: Implement standard-library parsing**

Use `email.policy.default`, `email.header.decode_header`, `email.utils`, and a small `HTMLParser` subclass. Normalize whitespace and retain visible link text plus the HTTP(S) destination where useful.

Safety rules:

- never fetch remote HTML resources;
- ignore `script`, `style`, `noscript`, and hidden tracking pixels;
- do not execute converters or subprocesses;
- reject `file:`, `javascript:`, and `data:` link targets;
- normalize path separators and control characters in attachment display names;
- enforce `EMAIL_MAX_BODY_CHARS` after decoding and normalization;
- construct a deterministic fallback ID from stable safe headers plus raw-message hash if `Message-ID` is missing.

- [ ] **Step 5: Run focused tests**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_parser.py -v
```

- [ ] **Step 6: Commit**

```bash
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_parser.py qq-ai-bridge/tests/test_email_parser.py qq-ai-bridge/tests/fixtures/email
git commit -m "feat: add safe email mime parser"
```

## Task 3: Implement a read-only, bounded IMAP client

**Files:**

- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_imap_service.py`
- Create: `qq-ai-bridge/tests/test_email_imap_service.py`

- [ ] **Step 1: Write failing IMAP tests with a fake connection**

The fake records every command. Cover:

```python
class EmailImapServiceTests(unittest.TestCase):
    def test_connects_with_ssl_and_timeout(self): ...
    def test_logs_in_and_selects_mailbox_readonly(self): ...
    def test_search_uses_since_and_before_end_plus_one(self): ...
    def test_fetches_newest_ids_up_to_limit(self): ...
    def test_empty_search_returns_empty_list(self): ...
    def test_partial_fetch_failure_is_reported_without_secret(self): ...
    def test_logout_runs_after_parser_failure(self): ...
    def test_client_never_calls_store_copy_move_or_expunge(self): ...
```

- [ ] **Step 2: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_imap_service.py -v
```

- [ ] **Step 3: Implement the client**

Create a short-lived connection per digest request. Use:

```python
imaplib.IMAP4_SSL(host, port, timeout=timeout_seconds)
connection.login(username, password)
connection.select(mailbox, readonly=True)
connection.search(None, "SINCE", imap_since, "BEFORE", imap_before)
connection.fetch(message_id, "(RFC822)")
```

Translate Python inclusive date ranges to IMAP's inclusive `SINCE` and exclusive `BEFORE` by adding one day to `end_date`. Limit IDs before body fetch. Fetch newest first while returning envelopes in chronological order for summarization.

Define safe exceptions with stable codes:

- `email_config_error`;
- `email_auth_error`;
- `email_network_error`;
- `email_protocol_error`;
- `email_parse_error`.

Exception messages may contain host and mailbox names but never username, password, authorization material, or message body.

- [ ] **Step 4: Run focused tests**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_imap_service.py -v
```

- [ ] **Step 5: Commit**

```bash
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_imap_service.py qq-ai-bridge/tests/test_email_imap_service.py
git commit -m "feat: add read only imap email service"
```

## Task 4: Add atomic archive, digest cache, and retention

**Files:**

- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_archive_service.py`
- Create: `qq-ai-bridge/tests/test_email_archive_service.py`
- Modify: `.gitignore`

- [ ] **Step 1: Confirm ignore coverage before editing**

Run:

```bash
git check-ignore -v qq-ai-bridge/data/email/probe.json
```

If the existing `data/` rule covers the path, do not add a redundant ignore entry. Only modify `.gitignore` when the command shows the path is not ignored.

- [ ] **Step 2: Write failing storage tests using a temporary directory**

```python
class EmailArchiveServiceTests(unittest.TestCase):
    def test_archive_filename_is_hash_not_raw_message_id(self): ...
    def test_archive_json_contains_no_credential_fields(self): ...
    def test_write_is_atomic(self): ...
    def test_same_message_write_is_idempotent(self): ...
    def test_digest_cache_key_includes_range_and_model(self): ...
    def test_refresh_bypasses_digest_cache(self): ...
    def test_corrupt_cache_is_quarantined_and_rebuilt(self): ...
    def test_retention_deletes_only_expired_email_archive_files(self): ...
    def test_retention_never_escapes_email_data_root(self): ...
```

- [ ] **Step 3: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_archive_service.py -v
```

- [ ] **Step 4: Implement deterministic paths**

Use:

```text
qq-ai-bridge/data/email/archive/YYYY-MM-DD/<sha256-message-id>.json
qq-ai-bridge/data/email/digests/daily/YYYY-MM-DD.json
qq-ai-bridge/data/email/digests/weekly/YYYY-Www.json
qq-ai-bridge/data/email/digests/ranges/<start>_<end>_<cache-hash>.json
qq-ai-bridge/data/email/quarantine/<timestamp>-<filename>
```

Write JSON to a sibling temporary file, flush and `fsync`, then use `os.replace`. Resolve every deletion target and verify it remains below the configured email data root before removal.

Archive fields are limited to normalized envelope data and a schema version. Never serialize connection objects, raw MIME bytes, provider request objects, or credentials.

- [ ] **Step 5: Run focused tests and ignore check**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_archive_service.py -v
git check-ignore -v qq-ai-bridge/data/email/probe.json
```

- [ ] **Step 6: Commit**

```bash
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_archive_service.py qq-ai-bridge/tests/test_email_archive_service.py .gitignore
git commit -m "feat: add private email archive and cache"
```

If `.gitignore` did not need a change, omit it from `git add`.

## Task 5: Build a tool-free, bounded email summary agent

**Files:**

- Create: `qq-ai-bridge/apps/qq_ai_bridge/services/email_digest_service.py`
- Create: `qq-ai-bridge/tests/test_email_digest_service.py`
- Modify: `qq-ai-bridge/shared/ai/agent_runtime.py`
- Modify: `qq-ai-bridge/tests/test_agent_runtime.py`

- [ ] **Step 1: Write digest-service tests**

Patch IMAP, archive, and `AgentRuntime`. Cover:

```python
class EmailDigestServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_empty_mailbox_returns_deterministic_no_mail_digest(self): ...
    async def test_cache_hit_does_not_call_imap_or_model(self): ...
    async def test_refresh_fetches_and_resummarizes(self): ...
    async def test_total_content_is_capped_before_model_call(self): ...
    async def test_summary_run_receives_no_tools(self): ...
    async def test_prompt_marks_email_content_as_untrusted_data(self): ...
    async def test_prompt_injection_inside_email_cannot_enable_tools(self): ...
    async def test_source_message_ids_are_preserved(self): ...
    async def test_model_failure_does_not_write_success_cache(self): ...
```

- [ ] **Step 2: Add an explicit no-tools runtime route test**

In `test_agent_runtime.py`, assert that route `email_summary` rejects any non-empty allowed-tool list. This invariant prevents an email body from inducing browser, web-search, or computer actions.

- [ ] **Step 3: Run and confirm failures**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_digest_service.py qq-ai-bridge/tests/test_agent_runtime.py -v
```

- [ ] **Step 4: Implement digest orchestration**

`EmailDigestService.build_digest(query)` performs:

1. validate the range and cache key;
2. return a valid cache hit unless `refresh=True`;
3. fetch normalized messages;
4. archive normalized messages;
5. build a bounded input that clearly separates instructions from untrusted email data;
6. call `AgentRuntime` with route `email_summary`, empty compact context, and `allowed_tool_names=()`;
7. validate and format final text;
8. write the digest cache only after complete success.

The summary instruction requires this stable QQ-oriented shape:

```text
邮件摘要：<period>（共 N 封）

重要/紧急：
- <item or 无>

需要我行动：
- <action, deadline, source subject>

其他信息：
- <short grouped items>

来源邮件：
- <date> | <sender> | <subject>
```

The model must not obey instructions embedded in email content. It summarizes them as data. It receives no tools and cannot initiate external actions.

- [ ] **Step 5: Enforce content budgets**

Before the model call:

- cap message count;
- cap each normalized body;
- cap combined input;
- preserve subject, sender, and date for every included item;
- if truncation occurs, include a deterministic notice in the digest metadata and user output;
- prefer newest messages when the total cap is reached.

- [ ] **Step 6: Run focused tests**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_digest_service.py qq-ai-bridge/tests/test_agent_runtime.py -v
```

- [ ] **Step 7: Commit**

```bash
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_digest_service.py qq-ai-bridge/shared/ai/agent_runtime.py qq-ai-bridge/tests/test_email_digest_service.py qq-ai-bridge/tests/test_agent_runtime.py
git commit -m "feat: summarize email with tool free agent"
```

## Task 6: Add the owner-only EmailSkill before ChatSkill

**Files:**

- Create: `qq-ai-bridge/apps/qq_ai_bridge/skills/email.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/skills/registry.py`
- Create: `qq-ai-bridge/tests/test_email_skill.py`
- Modify: `qq-ai-bridge/tests/test_chat_skill.py`

- [ ] **Step 1: Write failing skill tests**

```python
class EmailSkillTests(unittest.TestCase):
    def test_registry_places_email_before_chat(self): ...
    def test_disabled_feature_does_not_match(self): ...
    def test_non_owner_private_user_is_rejected(self): ...
    def test_group_message_does_not_match(self): ...
    def test_explicit_command_is_enqueued(self): ...
    def test_status_does_not_contact_imap(self): ...
    def test_help_is_deterministic(self): ...
    def test_invalid_email_subcommand_returns_help(self): ...
    def test_plain_chat_containing_email_word_falls_through(self): ...
    def test_queue_full_returns_busy_without_starting_work(self): ...
```

- [ ] **Step 2: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_skill.py -v
```

- [ ] **Step 3: Implement the skill**

`EmailSkill.can_handle` returns true only when:

- feature is enabled;
- message is private;
- user ID equals `OWNER_QQ`;
- the deterministic command parser returns anything other than `no_match`.

`handle` behavior:

- `help`: return help text synchronously;
- `status`: return enabled/provider/last-success states without secrets;
- `invalid`: return the exact accepted command list;
- `query`: admit one job to the repository's bounded background work path, immediately return/sends a short acknowledgement, then send the final digest through NapCat.

Do not perform network or model work on the webhook thread. Ensure a final reply is sent once, not both by the skill and webhook adapter.

- [ ] **Step 4: Insert the skill in the registry**

Place:

```python
("apps.qq_ai_bridge.skills.email", "EmailSkill"),
```

immediately before `ChatSkill`. It may be after other strongly explicit skills, but a matching email command must never reach general chat.

- [ ] **Step 5: Run skill and routing regressions**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_skill.py qq-ai-bridge/tests/test_chat_skill.py -v
```

- [ ] **Step 6: Commit**

```bash
git add qq-ai-bridge/apps/qq_ai_bridge/skills/email.py qq-ai-bridge/apps/qq_ai_bridge/skills/registry.py qq-ai-bridge/tests/test_email_skill.py qq-ai-bridge/tests/test_chat_skill.py
git commit -m "feat: add owner private email commands"
```

## Task 7: Extend the existing scheduler with daily and weekly digest jobs

**Files:**

- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/scheduler.py`
- Modify: `qq-ai-bridge/apps/qq_ai_bridge/services/reminder_store.py`
- Create: `qq-ai-bridge/tests/test_email_scheduler.py`
- Modify: `qq-ai-bridge/tests/test_schedule_service.py`

- [ ] **Step 1: Write deterministic scheduler tests**

Patch the clock, digest service, and `send_private_msg`. Use temporary scheduler-state storage.

```python
class EmailSchedulerTests(unittest.TestCase):
    def test_daily_job_waits_until_configured_time(self): ...
    def test_daily_job_uses_today_range(self): ...
    def test_weekly_job_runs_only_on_configured_weekday(self): ...
    def test_weekly_job_uses_monday_through_sunday_range(self): ...
    def test_successful_daily_send_is_idempotent_across_restart(self): ...
    def test_successful_weekly_send_is_idempotent_across_restart(self): ...
    def test_failed_napcat_send_does_not_mark_token(self): ...
    def test_digest_failure_does_not_mark_token(self): ...
    def test_disabled_jobs_do_not_contact_imap(self): ...
    def test_scheduled_run_never_enables_computer_or_web_tools(self): ...
```

- [ ] **Step 2: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_scheduler.py -v
```

- [ ] **Step 3: Generalize state tokens without breaking existing jobs**

If `SchedulerStateStore` exposes only `was_daily_sent`/`mark_daily_sent`, add generic methods while preserving old wrappers:

```python
def was_job_sent(self, task_key: str, token: str) -> bool: ...
def mark_job_sent(self, task_key: str, token: str, sent_at: datetime) -> None: ...

def was_daily_sent(...):
    return self.was_job_sent(...)
```

This is a behavior-preserving refactor for sleep and tomorrow-schedule jobs. Run their existing tests immediately after the change.

- [ ] **Step 4: Implement due-job helpers**

Add separate functions that are testable without starting the scheduler thread:

```python
def _run_email_daily_digest(now: datetime) -> None: ...
def _run_email_weekly_digest(now: datetime) -> None: ...
def _build_email_daily_token(now: datetime) -> str: ...
def _build_email_weekly_token(now: datetime) -> str: ...
```

Token formats:

```text
email_daily:2026-07-20
email_weekly:2026-W30
```

Only mark the token after both digest creation and NapCat send report success. Use `OWNER_QQ`; never send scheduled summaries to a group.

- [ ] **Step 5: Preserve restart catch-up semantics**

If the service starts after the scheduled time and the token has not succeeded, run once. If a successful token exists, skip. Weekly catch-up is limited to the current ISO week; do not send a backlog of historical weeks automatically.

- [ ] **Step 6: Run scheduler tests**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_scheduler.py qq-ai-bridge/tests/test_schedule_service.py -v
```

- [ ] **Step 7: Commit**

```bash
git add qq-ai-bridge/apps/qq_ai_bridge/services/scheduler.py qq-ai-bridge/apps/qq_ai_bridge/services/reminder_store.py qq-ai-bridge/tests/test_email_scheduler.py qq-ai-bridge/tests/test_schedule_service.py
git commit -m "feat: schedule qq email digests"
```

## Task 8: Add diagnostics, retention execution, and operator documentation

**Files:**

- Create: `qq-ai-bridge/scripts/email_agent_check.py`
- Create: `qq-ai-bridge/tests/test_email_agent_check.py`
- Create: `docs/install/qq-email-agent.md`
- Modify: `docs/install/run.md`
- Modify: `README.md`

- [ ] **Step 1: Write diagnostics-script tests**

The command is non-interactive and supports:

```bash
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/email_agent_check.py --config
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/email_agent_check.py --imap
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/email_agent_check.py --query today --dry-run
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/email_agent_check.py --cleanup --dry-run
```

Test contracts:

- `--help` and `--config` require no network and no configured secret;
- output uses masked username and `set`/`missing` for the password;
- `--imap` selects the mailbox read-only and fetches no bodies;
- `--query ... --dry-run` reports matching message count and date range without model use;
- cleanup dry-run lists only paths under the email data root;
- no operation asks for stdin input.

- [ ] **Step 2: Run and confirm failure**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_agent_check.py -v
```

- [ ] **Step 3: Implement diagnostics and bounded cleanup**

Use the same configuration, query, IMAP, and archive services as production. Do not duplicate parsing logic. Exit codes:

- `0`: check passed;
- `1`: configuration or connectivity failure;
- `2`: valid command but feature/capability disabled.

- [ ] **Step 4: Write the operator guide**

`docs/install/qq-email-agent.md` must include:

1. mailbox policy/privacy warning for cloud model processing;
2. creation of an IMAP client-specific password;
3. remote secret-file variables and `chmod 600`;
4. config-only and read-only IMAP checks;
5. the accepted QQ commands;
6. daily/weekly defaults and configuration;
7. data layout and retention;
8. log/trace redaction guarantees and limitations;
9. staged enablement: on-demand, then daily, then weekly;
10. immediate rollback flags;
11. explicit statement that no SMTP or mail mutation exists in Phase A.

- [ ] **Step 5: Run focused tests**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest qq-ai-bridge/tests/test_email_agent_check.py -v
PYTHONPATH=qq-ai-bridge python qq-ai-bridge/scripts/email_agent_check.py --help
```

- [ ] **Step 6: Commit**

```bash
git add qq-ai-bridge/scripts/email_agent_check.py qq-ai-bridge/tests/test_email_agent_check.py docs/install/qq-email-agent.md docs/install/run.md README.md
git commit -m "docs: add qq email agent operations guide"
```

## Task 9: Run Phase A email verification and remote canary

**Files:**

- Verify only; no new files unless a discovered defect requires a focused test and fix.

- [ ] **Step 1: Run the complete focused email suite**

```bash
PYTHONPATH=qq-ai-bridge python -m unittest \
  qq-ai-bridge/tests/test_email_config.py \
  qq-ai-bridge/tests/test_email_query_service.py \
  qq-ai-bridge/tests/test_email_parser.py \
  qq-ai-bridge/tests/test_email_imap_service.py \
  qq-ai-bridge/tests/test_email_archive_service.py \
  qq-ai-bridge/tests/test_email_digest_service.py \
  qq-ai-bridge/tests/test_email_skill.py \
  qq-ai-bridge/tests/test_email_scheduler.py \
  qq-ai-bridge/tests/test_email_agent_check.py \
  qq-ai-bridge/tests/test_agent_runtime.py \
  qq-ai-bridge/tests/test_private_chat_service.py \
  qq-ai-bridge/tests/test_chat_skill.py \
  qq-ai-bridge/tests/test_schedule_service.py -v
```

Expected: every listed test passes.

- [ ] **Step 2: Run repository checks**

```bash
bash run_ruff.sh
bash run_ruff_2.sh
git diff --check
git status --short
```

Expected: checks pass and the working tree contains only intentional changes.

- [ ] **Step 3: Review the diff for forbidden content**

```bash
rg -n "smtp|smtplib|html2markdown\.exe|codebuddy|permission-mode|input\(" \
  qq-ai-bridge/apps/qq_ai_bridge/services/email_* \
  qq-ai-bridge/apps/qq_ai_bridge/skills/email.py \
  qq-ai-bridge/scripts/email_agent_check.py
```

Expected: no matches. If documentation refers to excluded upstream components, keep the scan scoped to implementation files as shown.

- [ ] **Step 4: Review for accidental secrets or personal email content**

```bash
git diff --cached --check
git grep -n -E "sk-[A-Za-z0-9_-]{16,}|Authorization: Bearer|EMAIL_IMAP_PASSWORD=.+|RESPONSES_PROXY_API_KEY=.+|OPENAI_API_KEY=.+"
```

Expected: no real secret values. Empty `.env.example` assignments are allowed.

- [ ] **Step 5: Perform the remote canary in stages**

After code review and explicit deployment approval:

```text
Stage 1 — configuration only
- Install pinned dependencies in the existing virtual environment.
- Add secrets to ~/.candace/qq-ai-bridge.env and chmod 600.
- Run config and read-only IMAP diagnostics.
- Keep EMAIL_AGENT_ENABLED=false.

Stage 2 — on-demand owner commands
- Enable EMAIL_AGENT_ENABLED only.
- Restart the bridge with the repository's documented user-service command.
- Send 邮件 状态, 邮件 今天, 邮件 昨天, 邮件 本周.
- Verify no duplicate QQ sends, no body text in logs, and expected API usage.

Stage 3 — daily schedule
- Enable EMAIL_DAILY_DIGEST_ENABLED.
- Keep weekly disabled for at least three successful daily runs.
- Restart once after the send time and verify the daily idempotency token prevents duplicates.

Stage 4 — weekly schedule
- Enable EMAIL_WEEKLY_DIGEST_ENABLED.
- Verify one current-week send and one restart skip.
```

- [ ] **Step 6: Verify rollback**

Set:

```dotenv
EMAIL_DAILY_DIGEST_ENABLED=false
EMAIL_WEEKLY_DIGEST_ENABLED=false
EMAIL_AGENT_ENABLED=false
```

Restart the bridge and confirm ordinary private and group QQ behavior continues. Disabling email must not require disabling the Agents SDK chat canary.

- [ ] **Step 7: Record the final verification commit**

If no fixes were required, no empty commit is needed. If verification produced focused fixes and tests:

```bash
git status --short
git add qq-ai-bridge/apps/qq_ai_bridge/services/email_digest_service.py qq-ai-bridge/tests/test_email_digest_service.py
git commit -m "fix: harden qq email digest canary"
```

The two paths above illustrate a digest-service regression fix. If verification changed different files, replace that `git add` invocation with the exact reviewed paths printed by `git status --short`; never stage unrelated work.

## Phase A completion gate

The phase is complete only when:

- owner-private on-demand commands work for every documented range;
- IMAP is selected read-only and no mutating command exists;
- no CodeBuddy subprocess, Windows converter, stdin prompt, or SMTP dependency was ported;
- summary runs expose zero tools;
- email prompt injection cannot invoke web search or PC Agent actions;
- daily and weekly state survive restart without duplicate QQ delivery;
- logs and traces contain no full email body or credential;
- the live API/provider dashboard confirms understood token/tool charges;
- feature flags independently roll back chat runtime, on-demand email, daily digest, and weekly digest.

## Reference material

- [Campus_Exmail_Agent](https://github.com/jytpeterjiang/Campus_Exmail_Agent)
- `docs/superpowers/specs/2026-07-20-phase-a-openai-agents-sdk-email-design.md`
- `docs/superpowers/plans/2026-07-20-openai-agents-sdk-foundation.md`
- [OpenAI Agents SDK overview](https://developers.openai.com/api/docs/guides/agents)
- [OpenAI provider compatibility](https://openai.github.io/openai-agents-python/models/)
