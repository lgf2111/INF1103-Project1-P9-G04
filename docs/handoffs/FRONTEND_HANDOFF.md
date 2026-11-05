# Frontend handoff: message assessment experience

This handoff is for the frontend teammate implementing the missing product
screens in the existing Python/PySide6 desktop GUI. It follows the product
direction discussed for this phase; it is not a claim that the proposed
assessment services or report-history functions already exist.

## UI/UX goals

Make the experience feel quick, clear, and reassuring. A user should be able
to submit a suspicious message without learning security jargon, understand
the outcome without interpreting a score, and know what to do next.

- Use a single-window flow with shallow navigation and a clear primary action.
- Make the message editor large and paste-friendly. Keep Email / SMS / Chat
  selection easy to find, not visually dominant.
- Keep the form on one page for the first implementation. Reveal follow-up
  questions only when relevant instead of adding unnecessary wizard steps.
- Keep labels, button placement, and terminology consistent across screens.
- Use calm, accessible styling. Never rely on color alone to communicate risk
  or use alarmist visuals.

## Product direction

- **Initial users:** people at small businesses who do not have a dedicated
  security specialist available for every suspicious message.
- **Job to be done:** help a user quickly understand why an email, SMS, or chat
  message may be suspicious and choose a safe next step.
- **Product promise:** “Know what to do next—not just whether a message looks
  suspicious.”
- **Experience principles:** plain language, evidence tied to the submitted
  message, practical next steps, and honest uncertainty. Do not imply that
  PhishReport can prove a message is safe.
- **Initial scope:** a useful single-user assessment flow. Team dashboards,
  shared queues, incident management, and real account settings are not part
  of this handoff.

Keep the existing CLI working. The GUI is a separate desktop client; the
Docker-hosted GUI continues to show that desktop window through noVNC during
the migration. The target desktop app is one Python process: GUI screens call
shared application services in-process. The GUI must not start a second
assessment server or launch the CLI as a subprocess.

## Existing implementation and gap

Already implemented:

- Sign-in, registration, password-reset screens, and an authentication HTTP
  client in `main.py` and `auth_api.py`.
- An empty signed-in Overview shell, profile menu, locked Settings screen, and
  sign-out.
- CLI assessment flows for manual email/SMS/chat text, `.eml` folder import,
  and browser upload; the CLI also asks about message links/files and user
  actions.
- Rule-based assessment results containing `score`, `priority`, `reasons`, and
  `checklist`.
- Local JSON report history in the CLI.

Not implemented in the desktop GUI:

- Message entry, `.eml` import, exposure questions, or analysis.
- Assessment results and their recommended actions.
- A saved-report list or report detail view.

The desktop `AuthApiClient` only implements authentication over HTTP. That
current authentication prototype is separate from assessment and does not
mean the GUI needs an HTTP backend to analyze messages. The
[`BACKEND_HANDOFF.md`](./BACKEND_HANDOFF.md) defines the proposed in-process
service contract; assessment and report-history GUI integration are not
implemented yet. Do not call the interactive CLI entry points from a widget:
they prompt on stdin and mix application work with terminal presentation.
Call reusable services instead, and run slow work in Qt workers so the event
loop stays responsive.

## Frontend scope and priority

### P0: turn Overview into a useful starting point

- Replace the empty Overview with a short welcome and a prominent **Check a
  message** action.
- Provide shallow navigation to Overview, Check a message, and Reports. Keep
  the existing profile menu and sign-out behavior.
- If no history is available, show a calm empty state that explains what the
  user can do next; do not imply reports already exist.
- Until history support is implemented, disable Reports with a clear
  explanation rather than showing a fake or empty success state.

### P0: submit an assessment

Build a guided form with:

1. **Message type:** Email, SMS, or Chat.
2. **Message content:** a large, paste-friendly multi-line editor that rejects
   blank content, preserves the submitted text, and scrolls predictably for
   long messages.
3. **Sender (optional):** do not claim that the sender has been authenticated.
4. **Email import:** allow choosing one `.eml` file for email. The existing
   parser supports text/HTML email content, rejects other file types, limits
   uploads to 2 MiB, and does not analyse attachments or embedded images.
   Reuse/refactor the established parser rather than creating a second parser.
5. **Exposure context:** ask whether a link or file was present, then ask
   whether the user clicked or downloaded only when applicable. Ask whether
   they submitted a password or one-time code. Match the current domain
   contract; do not silently substitute “No” when an answer is unknown.
6. **Submit:** use a clear action such as **Check message**. Before sending,
   explain where the message is processed and retained using the service
   owners' confirmed data policy. The current CLI sends assessment input to
   its AI provider and stores reports locally; do not promise privacy or
   deletion behavior that the chosen service does not guarantee.

Keep form validation specific and near the relevant field. Preserve the form
when a request fails so the user can correct or retry it.

Support keyboard navigation, visible focus, sensible tab order, readable type,
and sufficient contrast. Keep primary actions visible without hiding content
or trapping focus.

### P0: explain the result and next step

Present the returned priority, reasons, and checklist in a clear hierarchy:

- Show **HIGH**, **MEDIUM**, or **LOW** as a response priority.
- If the numeric score is shown, label it a **rule-based response-priority
  score**, not a probability or confidence percentage. Avoid probability
  gauges.
- Explain the reasons in plain language, using the result's supplied reasons
  rather than inventing indicators.
- Make the recommended checklist easy to follow. Do not replace it with
  frontend-generated security advice.
- State that a LOW result does not guarantee that a message is safe.
- Offer **Check another message** and a route back to Overview.
- Lead with the most useful next step, not a numeric score. If the score is
  included, make it secondary and explain what it represents.

Use restrained, accessible emphasis rather than alarmist visuals. HIGH should
be prominent, but color must not be the only way priority is conveyed.

### P1: saved reports

When backend support and a privacy/retention decision are available, implement:

- A Reports list with loading, empty, error, and populated states.
- A concise row/card with channel, date, priority, and a safely shortened
  preview.
- A detail view showing the full message only when the user opens a report,
  its assessment reasons, and its recommended actions.
- Explicit behavior for refresh, pagination, unavailable/deleted records,
  deletion confirmation, and save failures.
- Loading, empty, network-error, and populated states. Avoid exposing full
  message content in list previews or notifications.

The current version-2 local report format stores `schema_version`, `channel`,
`message`, and `result`; it has no stable report ID or timestamp. Do not assume
that this is sufficient for a server-backed history list. Confirm the
identifier, timestamps, retention, ownership, and deletion behavior with the
backend teammate.

## Suggested user flow

Sign in → Overview → Check a message → choose type and enter/import content →
answer relevant exposure questions → submit → view priority, reasons, and
checklist → start another check or return to Overview.

During submission, show progress and prevent accidental duplicate requests.
For network, validation, or service errors, show a user-safe explanation and
retain the draft. Never turn a failed or malformed response into a LOW result
or a success-shaped empty report.

The progress state should say what is happening in plain language. Keep Qt
responsive throughout; offer a retry when appropriate. Keep the result's main
action and return navigation easy to find, even when the message or checklist
is long.

## Backend integration to agree

These are frontend requirements to agree with the backend teammate. For the
local desktop app, the boundary is a typed Python service interface, not an
assessment HTTP API. The GUI and service functions run in the same process;
Qt workers keep slow assessment work off the UI thread.

1. Agree on the Python function signature and typed input/output for
   assessment, including channel, message, optional sender, and supported
   exposure context. Decide how the shared `.eml` parser is called.
2. Return a validated result matching the existing domain fields:
   `score` (integer), `priority` (`LOW`/`MEDIUM`/`HIGH`), `reasons` (strings),
   and `checklist` (strings).
3. Define typed validation and provider errors, cancellation/timeout behavior,
   and how a worker reports progress without touching widgets from its thread.
4. Decide how local reports are represented and loaded. Only choose
   server-backed history if there is a separate product requirement for
   accounts or shared data.
5. Confirm exactly what content is sent to the AI provider, where it is stored,
   for how long, and how those facts are explained to users. Avoid logging
   message contents, passwords, or one-time codes.

The existing CLI's 2 MiB `.eml` upload limit and supported formats are the
current behavior to preserve unless the backend owners agree on a change.

## Acceptance criteria

- The existing sign-in, registration, reset, avatar menu, locked Settings, and
  sign-out flows continue to work.
- A signed-in user can complete the assessment form for email, SMS, and chat;
  email import follows the existing `.eml` restrictions.
- Relevant exposure questions are collected without assuming an unanswered
  question means “No.”
- The GUI displays only a valid service assessment and communicates its
  priority, evidence, and recommended actions without presenting score as
  certainty.
- A LOW result is never described as proof of safety.
- Loading, empty, field-error, service-error, and successful states are
  designed and testable. Failed requests preserve the draft.
- Qt remains responsive during service calls; tests use a fake service and do
  not require live AI or authentication services.
- The Reports experience is not represented as available until the storage
  contract is agreed and implemented.

## Suggested implementation order

1. Add the Overview call-to-action and navigation while preserving auth
   behavior.
2. Agree on the in-process assessment service contract; implement the Qt
   worker seam, form, and result screen with fake-service tests.
3. Add `.eml` selection and shared parser integration.
4. Agree on report persistence and privacy; then implement list and detail
   views.

## References

- [`BACKEND_HANDOFF.md`](./BACKEND_HANDOFF.md) — in-process assessment
  contract, current authentication prototype, and data-handling requirements.
  An [HTML version](./BACKEND_HANDOFF.html) is also available.
- [`../../app_gui/README.md`](../../app_gui/README.md) — desktop GUI setup and module
  guide.
- [`../../README.md`](../../README.md) — CLI assessment, channels, report storage,
  and `.eml` behavior.
