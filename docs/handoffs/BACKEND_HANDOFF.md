# Backend handoff for Telegram

The CLI and Telegram launcher run the shared Python managers in their own
application process. Telegram currently calls `DataManager.load(strict=True)`
for its connection check. Keep the CLI usable while extracting the shared
assessment workflow from its terminal prompts and presentation.

The assessment and report contracts below are proposals for the next
milestones. See the [Telegram run guide](../../app_gui/README.md) for the
implemented connection check.

## In-process assessment service needed by the GUI (proposed)

The frontend needs a typed Python service boundary for assessment. It must not
call the CLI's interactive `check_message()` flow: that flow prompts on stdin
and mixes application work with terminal presentation. Extract the workflow
into reusable functions under `app_cli/` (for example `app_cli/services/`) and call
them directly from the Telegram process. Keep Telegram and terminal I/O out
of the service. Run slow AI or file operations off the bot's event loop.

### Assess a message

Agree on a typed Python input model. An illustrative shape is:

```python
AssessmentRequest(
    channel="email",
    message="Please review this unusual payment request.",
    sender="billing@example.test",
    has_link=True,
    link="https://example.test/pay",
    has_file=False,
    file_name=None,
    clicked=False,
    downloaded=False,
    submitted_category=None,
)
```

The service may use a dataclass or another existing project convention; this
is a contract example, not a required class name. `channel` is `email`,
`sms`, or `chat`; `sender` is optional. `link` and
`file_name` are optional and only meaningful when the corresponding
`has_link`/`has_file` value is true. Ask the user about clicks/downloads only
when applicable and transmit the answers explicitly. `submitted_category` is
`password`, `otp`, or `null` after the user answers the question. The backend
must reject contradictory or malformed combinations rather than silently
rewriting the user's answers.

Return a validated report/result object using the existing domain fields:

```python
AssessmentResult(
    score=45,
    priority="MEDIUM",
    reasons=["Example explanation from the assessment engine."],
    checklist=["Verify the request using a known official contact method."],
)
```

These names illustrate the contract; reuse existing model types where
available. The result fields match the existing domain contract: integer `score`
(0–100), `priority` (`LOW`, `MEDIUM`, or `HIGH`), and arrays of non-blank
strings `reasons` and `checklist` (the arrays themselves may be empty). The
score is a rule-based response-priority score, not a probability that the
message is malicious. Do not make the frontend infer a result from a partial
response.

The GUI should show an in-progress state, prevent duplicate submissions, and
remain responsive. Define validation/provider error types, timeouts, progress
reporting, and whether an in-flight call can be cancelled. Do not have a
worker send chat messages directly. Return results or errors to the handler
so the Telegram I/O manager owns presentation. If retries can create duplicate saved reports, define
how the service avoids that.

### Report history (proposed, required only if Reports is enabled)

For the private bot, use local persistence through reusable data
services. Agree on Python functions to list, load, and optionally delete
reports, along with stable identifiers and timestamps if needed. The GUI
should use the DataManager for history access and validation.

Define ordering, missing/deleted record behavior, and whether a successful
assessment is automatically saved. The existing CLI's local `reports.json`
format has no stable ID or timestamp; preserve compatibility or migrate it
deliberately rather than making the GUI assume a new schema.

### Errors and validation

Use typed service errors with a stable code, safe message, and optional
field-specific details. The frontend needs to distinguish:

- invalid input or field validation;
- message or email input exceeding a configured limit;
- AI provider unavailable or timed out;
- local persistence failure.

Never convert an AI, validation, or storage failure into a LOW result or an
empty success. Avoid exposing provider details, stack traces, secrets, or
submitted content in error messages.

## Email import and input limits

The existing CLI accepts `.eml` files up to 2 MiB and parses text and HTML
email content. Attachments and embedded images are outside its analysis scope.
Reuse the shared parser in-process and pass extracted fields to the assessment
service. The current message-text limit is 50,000 characters.

## Data handling, privacy, and operations

Before enabling assessment, provide product-approved answers for the frontend
to show near submission: whether the full message is sent to the AI provider,
where it is processed, whether it is persisted locally or remotely, who can
access it, the retention period, and how the user can delete it. Do not
promise privacy, retention, or deletion behavior that the service does not
enforce.

- Gate report and assessment handlers on the configured private chat.
- Keep message bodies, links, passwords, one-time codes, and bot tokens out of logs.
- Validate channel, lengths, optional sender and link/file metadata, and
  exposure answers in the service boundary.
- Apply provider timeouts and bounded input sizes in the local service. Add
  request rate limits only if an online service is adopted.
- Return only validated assessment output; do not expose raw model prompts,
  provider payloads, or internal exception details.
- Persist reports locally according to an agreed retention policy; support
  deletion consistently if that feature is provided.

## Frontend integration checklist

1. Agree on the in-process Python service signatures, result types, and typed
   errors; implement them by reusing existing logic and data managers.
2. Keep the service independent of Telegram and terminal input/output so both GUI
   and CLI can call it.
3. Decide local report persistence and migration behavior before enabling
   Reports.
4. Confirm email parsing, input limits, and user-facing data-handling copy.
5. Test success, validation, timeout, provider outage, persistence failure,
   and malformed results without live provider calls.
