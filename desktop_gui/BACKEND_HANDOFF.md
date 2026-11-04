# Backend handoff: desktop GUI

The desktop app is a Python/PySide6 client. It contains no account database, password verification, email delivery, assessment API, or server-side session logic. The CLI remains a separate entry point and is not changed by this GUI.

The authentication client is implemented in [`auth_api.py`](./auth_api.py). The GUI does not yet have assessment or report APIs. The auth and assessment contracts below are proposals for the backend and frontend teammates to agree on; do not treat proposed assessment endpoints as implemented.

## API contract

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

The client currently expects the API origin in `PHISHREPORT_API_URL`, defaulting to `http://127.0.0.1:8000`. Endpoint names, cookie policy, reset-link delivery, and registration verification behavior are proposed and should be agreed before backend integration.

`mock_auth_api.py` provides a local-only, fixed-response server for UI development. It is not the production backend: it has one hard-coded demo account, does not persist accounts or passwords, and does not send reset or verification email. Replace it with the real service while preserving the API contract above.

## Frontend boundary

`desktop_gui/main.py` implements the screens and presentation state. `desktop_gui/auth_api.py` is the HTTP boundary. After sign-in, the GUI shows an empty dashboard shell with an initials-based profile avatar. Its menu opens a locked Settings screen or signs out. Assessment and report features are reserved for later GUI phases. The current user response has no image field, so the avatar uses the account name's initials.

## Assessment API needed by the GUI (proposed)

The frontend needs an asynchronous service boundary for assessment. It must not
call the CLI's interactive `check_message()` flow: that flow prompts on stdin,
uses CLI presentation, and writes to local JSON. The service should reuse the
existing assessment logic and validated result shape without blocking the Qt
event loop.

### Submit an assessment

Proposed request:

```http
POST /api/assessments
Content-Type: application/json
Cookie: session=...
```

```json
{
  "channel": "email",
  "sender": "billing@example.test",
  "message": "Please review this unusual payment request.",
  "has_link": true,
  "link": "https://example.test/pay",
  "has_file": false,
  "file_name": null,
  "clicked": false,
  "downloaded": false,
  "submitted_category": null
}
```

`channel` is `email`, `sms`, or `chat`; `sender` is optional. `link` and
`file_name` are optional and only meaningful when the corresponding
`has_link`/`has_file` value is true. Ask the user about clicks/downloads only
when applicable and transmit the answers explicitly. `submitted_category` is
`password`, `otp`, or `null` after the user answers the question. The backend
must reject contradictory or malformed combinations rather than silently
rewriting the user's answers.

Proposed success response:

```json
{
  "report": {
    "id": "report-id",
    "createdAt": "2026-11-04T14:30:00Z",
    "channel": "email",
    "message": "Please review this unusual payment request.",
    "result": {
      "score": 45,
      "priority": "MEDIUM",
      "reasons": ["Example explanation from the assessment engine."],
      "checklist": ["Verify the request using a known official contact method."]
    }
  }
}
```

The `result` fields match the existing domain contract: integer `score`
(0–100), `priority` (`LOW`, `MEDIUM`, or `HIGH`), and arrays of non-blank
strings `reasons` and `checklist` (the arrays themselves may be empty). The
score is a rule-based response-priority score, not a probability that the
message is malicious. Do not make the frontend infer a result from a partial
response.

The desktop should show an in-progress state, prevent duplicate submissions,
and remain responsive. Set request limits and timeouts appropriate for AI
processing. Define whether a disconnected/cancelled request can still finish
server-side and how retries avoid accidental duplicate reports (for example,
an idempotency key).

### Report history (proposed, required only if Reports is enabled)

The frontend history design needs stable IDs, timestamps, channel, priority,
and a short message preview. Detail needs the full submitted message, reasons,
and checklist. Suggested endpoints:

| Method and path | Purpose |
| --- | --- |
| `GET /api/reports?limit=20&cursor=...` | Return the signed-in user's paginated report summaries and a next cursor. |
| `GET /api/reports/{id}` | Return one report detail owned by the signed-in user. |
| `DELETE /api/reports/{id}` | Delete one report if deletion is supported by the agreed retention policy. |

Every response must be scoped to the authenticated user. Define ordering,
pagination, missing/deleted record behavior, and whether a successful
assessment is automatically saved. The existing CLI's local `reports.json`
format has no stable ID or timestamp and is not a server-history contract.
Until these operations and the data policy are agreed and implemented, the
frontend should keep Reports disabled with an honest explanation.

### Errors and validation

Use the common JSON error envelope from the authentication contract, including
stable `code`, user-safe `message`, and optional `fieldErrors`. The frontend
needs to distinguish:

- `400`/`422`: invalid input or field validation.
- `401`: the session is missing or expired; return the user to sign-in without
  discarding their unsent draft.
- `413`: message or email upload exceeds a configured limit.
- `429`: rate limit, with a retry delay when available.
- `502`/`503`/`504`: analysis provider or service unavailable/timed out.

Never return an assessment-shaped response for an error, and never convert an
AI or validation failure into a LOW result. Avoid exposing provider details,
stack traces, secrets, or submitted content in error messages.

## Email import and input limits

The existing CLI accepts `.eml` files up to 2 MiB, supports text/HTML email
content, and does not analyse attachments or embedded images. Agree whether
the desktop parses locally using the shared parser or uploads the original
file. Prefer parsing locally and submitting the extracted fields when it
preserves the current security behavior; if uploading, enforce size/type
limits server-side and document how the raw file is handled. The current
message-text limit is 50,000 characters; coordinate any shared GUI/API limit
with the frontend.

## Data handling, privacy, and operations

Before enabling assessment, provide product-approved answers for the frontend
to show near submission: whether the full message is sent to the AI provider,
where it is processed, whether it is persisted, who can access it, the
retention period, and how the user can delete it. Do not promise privacy,
retention, or deletion behavior that the service does not enforce.

- Require authentication for assessment/history unless the product owners
  explicitly decide otherwise. Never expose one user's history to another.
- Do not log message bodies, links, passwords, one-time codes, session cookies,
  or reset tokens. Redact request/exception telemetry.
- Validate channel, lengths, optional sender and link/file metadata, and
  exposure answers server-side.
- Apply request and provider timeouts, rate limits, and bounded request sizes.
- Return only validated assessment output; do not expose raw model prompts,
  provider payloads, or internal exception details.
- Persist reports only according to the agreed retention policy; support
  deletion consistently across primary storage, caches, and exports where
  applicable.

## Frontend integration checklist

1. Confirm the auth endpoints, cookie behavior, registration verification,
   reset delivery, and session expiry.
2. Agree on the assessment request/result/error schemas and implement a
   development assessment endpoint or mock for GUI work.
3. Decide server-backed versus local-only report history; do not expose
   Reports until the choice and data lifecycle are implemented.
4. Confirm email parse/upload behavior, input limits, and user-facing data
   handling copy.
5. Test success, validation, authentication expiry, rate limiting, timeout,
   provider outage, and malformed responses without live provider calls.

`mock_auth_api.py` is a local-only, fixed-response authentication server; it
does not implement assessment or report history. Extend it only as a separate
development feature if frontend work needs those responses. It is not a
production backend.
