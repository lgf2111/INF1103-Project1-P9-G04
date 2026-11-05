# Backend handoff: desktop GUI

## Target architecture: one local desktop app

The migration target is one Python desktop application process, not a GUI plus a separate assessment server. Backend teammates should make reusable application services in `app_cli/`; frontend teammates should call those Python functions directly from `app_gui/`. Slow calls run in Qt worker threads so the interface remains responsive. The GUI must not start `app_cli/main.py` as a subprocess or call the interactive CLI menu.

Keep the existing analysis, rules, AI integration, parser, and persistence code. Extract or wrap the needed workflows behind a small service boundary (for example `app_cli/services/`) rather than rewriting the application in a new folder. Keep `app_cli/main.py` as a CLI adapter during migration; both CLI and GUI can call the shared services until the GUI reaches feature parity.

**Current implementation status:** the GUI assessment and report screens are not integrated with these services yet. The authentication screens currently use an HTTP client and a development-only mock auth server. That prototype is separate from assessment; it does not make an HTTP assessment backend necessary. Whether real online accounts are a product requirement remains a separate decision.

The service contracts and examples below are proposals to agree on, not claims that the functions or APIs already exist.

## Optional authentication API contract

This section documents the current authentication prototype only. It is not the architecture for local message analysis. If the team decides to keep online user accounts, backend owners can implement this contract as a separate service. If the product is local-only, decide whether to replace or remove the current auth screens/client rather than making assessment depend on an account server.

All requests and successful non-empty responses use JSON. Errors use this shape:

```json
{
  "error": {
    "code": "INVALID_CREDENTIALS",
    "message": "Email or password is incorrect.",
    "fieldErrors": {
      "email": "Enter a valid email address."
    }
  }
}
```

`fieldErrors` is optional and maps request field names to user-facing text.

| Method and path | Request body | Success response |
| --- | --- | --- |
| `POST /api/auth/login` | `{ "email": "...", "password": "..." }` | `200 { "user": { "id": "...", "email": "...", "name": "..." } }` |
| `POST /api/auth/register` | `{ "email": "...", "password": "..." }` | `201 { "verificationRequired": true }`, or `201 { "verificationRequired": false, "user": { "id": "...", "email": "...", "name": "..." } }` |
| `POST /api/auth/password/reset-request` | `{ "email": "..." }` | `202 { "message": "If an account matches, reset instructions will be sent." }` |
| `POST /api/auth/password/reset` | `{ "token": "...", "password": "..." }` | `200 { "message": "Password updated." }` |
| `GET /api/auth/me` | No body | `200 { "user": { "id": "...", "email": "...", "name": "..." } }` |
| `POST /api/auth/logout` | No body | `204 No Content` (or `200` with a JSON body) |

`name` is optional. When account verification is required, the backend must not create a signed-in session. The desktop app shows an account-safe verification confirmation. When registration signs the user in immediately, return `verificationRequired: false`, the `user`, and the session cookie.

## Session and security requirements

- The client uses Python's in-memory `CookieJar`; it does not persist session cookies, passwords, or reset tokens to disk. Closing the desktop app ends the local session.
- Prefer a short-lived, opaque, server-side session cookie with `HttpOnly`, `Secure` in production, and an appropriate `SameSite` policy. Invalidate the session on logout and password changes.
- Require HTTPS except for local development. Validate certificate chains; do not disable TLS checks.
- Use generic responses for login and password-reset requests so they do not disclose whether an email is registered. Rate-limit login, registration, and reset-request endpoints.
- Reset tokens must be random, short-lived, single-use, and invalidated after reset. The email link should open the app with its token (register a `phishreport://reset` URL scheme when packaging); during development, pass it with `--reset-token`.
- New passwords must be at least 12 characters to match client-side validation. The backend remains authoritative and should return a field error when its password policy rejects a value.
- Never return password hashes, session secrets, reset tokens (other than the intended email link), or internal exception details in API responses.

The current auth client expects the API origin in `PHISHREPORT_API_URL`, defaulting to `http://127.0.0.1:8000`. Endpoint names, cookie policy, reset-link delivery, and registration verification behavior are proposals that require agreement before implementing real online accounts.

`mock_auth_api.py` provides a local-only, fixed-response server for UI development. It has one hard-coded demo account, does not persist accounts or passwords, and does not send reset or verification email. It is not an assessment backend or a production account service.

## Frontend boundary

`app_gui/main.py` implements screens and presentation state. `app_gui/auth_api.py` is currently the HTTP boundary for the optional authentication prototype only. After sign-in, the GUI shows an empty dashboard shell with an initials-based profile avatar. Its menu opens a locked Settings screen or signs out. Assessment and report features are reserved for later GUI phases. The current user response has no image field, so the avatar uses the account name's initials.

## In-process assessment service needed by the GUI (proposed)

The frontend needs a typed Python service boundary for assessment. It must not
call the CLI's interactive `check_message()` flow: that flow prompts on stdin
and mixes application work with terminal presentation. Extract the workflow
into reusable functions under `app_cli/` (for example `app_cli/services/`) and call
them directly from the GUI process. Keep the service independent of Qt; use
Qt workers in `app_gui/` to run slow AI or file work without blocking the
event loop.

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
worker access widgets directly; return results or errors to the GUI thread
through Qt signals. If retries can create duplicate saved reports, define
how the service avoids that.

### Report history (proposed, required only if Reports is enabled)

For the local desktop app, prefer local persistence through reusable data
services. Agree on Python functions to list, load, and optionally delete
reports, along with stable identifiers and timestamps if needed. The GUI
should not manipulate `reports.json` directly or duplicate its schema.

Only use server-backed history if accounts/shared data are a confirmed product
requirement. In that case, specify ownership, stable IDs, timestamps,
pagination, retention, and deletion separately; those endpoints are not part
of the one-process local assessment architecture.

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
submitted content in error messages. If optional online authentication is
retained, handle session expiry in its separate auth boundary without losing
the user's unsent draft.

## Email import and input limits

The existing CLI accepts `.eml` files up to 2 MiB, supports text/HTML email
content, and does not analyse attachments or embedded images. Agree whether
the desktop parses locally using the shared parser; the target local app
should parse in-process and pass extracted fields to the assessment service,
not upload the original file to an HTTP server. The current message-text limit
is 50,000 characters; coordinate the limit with the frontend.

## Data handling, privacy, and operations

Before enabling assessment, provide product-approved answers for the frontend
to show near submission: whether the full message is sent to the AI provider,
where it is processed, whether it is persisted locally or remotely, who can
access it, the retention period, and how the user can delete it. Do not
promise privacy, retention, or deletion behavior that the service does not
enforce.

- Treat local assessment as independent from the current demo sign-in. Require
  online authentication only if product owners explicitly choose accounts or
  shared data; never expose one user's remote history to another.
- Do not log message bodies, links, passwords, one-time codes, session cookies,
  or reset tokens. Redact request/exception telemetry.
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
2. Keep the service independent of Qt and terminal input/output so both GUI
   and CLI can call it.
3. Decide local report persistence and migration behavior before enabling
   Reports.
4. Confirm email parsing, input limits, and user-facing data-handling copy.
5. Test success, validation, timeout, provider outage, persistence failure,
   and malformed results without live provider calls.
6. Separately decide whether real online authentication is required. If so,
   agree on the auth HTTP contract and test session expiry and account flows.

`mock_auth_api.py` is a local-only, fixed-response authentication server; it
does not implement assessment or report history. Extend it only as a separate
development feature if frontend work needs those responses. It is not a
production backend.
