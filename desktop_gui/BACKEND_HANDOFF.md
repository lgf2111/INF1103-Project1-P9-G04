# Backend handoff: desktop authentication

The desktop app is a Python/PySide6 client. It contains no account database, password verification, email delivery, or server-side session logic. The CLI remains a separate entry point and is not changed by this GUI.

The client contract is implemented in [`auth_api.py`](./auth_api.py). Confirm these proposed endpoints and payloads with the backend implementation before integration.

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

`desktop_gui/main.py` implements the screens and presentation state. `desktop_gui/auth_api.py` is the HTTP boundary. The post-login screen is deliberately a placeholder: assessment and report features are reserved for later GUI phases.
