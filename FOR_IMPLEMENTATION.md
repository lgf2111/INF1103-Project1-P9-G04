# For Implementation: Telegram and Feedback Workflow

## Purpose

This note is a handover for completing the assessment trace and feedback work
through both the CLI and a Telegram bot. It records the current contracts,
required integration points, and decisions to settle before implementation.

## Assignment alignment

- A user review/correction workflow is explicitly listed in the Phase 2 brief as
  an example of a meaningful new feature.
- Team decision: the Telegram bot is the selected GUI/advanced feature; the
  feedback and correction workflow is the meaningful new feature.
- AI must remain part of every assessment. Feedback must not bypass the AI
  manager or silently alter the rule-based score.
- The four manager responsibilities must remain identifiable. CLI and Telegram
  should be interface adapters that reuse shared application services.
- The required OOP classes should remain purposeful and be kept in separate
  files, as instructed for this project.
- Demonstrate the Telegram bot as an interactive user-facing interface and
  describe its GUI scope in the engineering report.

## Current implementation

- `LogicManager.evaluate(record)` returns a JSON-compatible dictionary with
  `score`, `priority`, `reasons`, `checklist`, `matched_rule`, and `trace`.
- `trace` is an ordered list of rule checks up to and including the first
  matching rule. Each item has `rule_name`, `matched`, and `score` (`null` for
  a non-matching rule).
- `io_manager.display_result()` renders the trace in the CLI.
- `main.check_message()` still owns the CLI-oriented orchestration around input,
  AI, Logic Manager, saving, and display. A Telegram adapter should not call it
  directly because it collects terminal input and prints to the terminal.
- New assessments are saved in the strict version-2 report format. The current
  trace is shown for the live assessment but is not saved in report history.
- There is no Telegram bot adapter, `FeedbackStore`, or correction workflow in
  the repository yet.

## Recommended implementation shape

1. Add an `AssessmentService` class in its own file. Move the shared
   AI-assessment, Logic Manager, and report-save flow behind this service so
   both CLI and Telegram can submit the same record and receive the same result.
2. Keep terminal prompts and printing in `io_manager.py`. The CLI should call
   `AssessmentService` and pass the result to the existing renderer.
3. Add a `TelegramBot` adapter in its own file. It should collect Telegram
   message/action input, call `AssessmentService`, and format the JSON-safe
   result for Telegram. Do not duplicate scoring rules or use terminal I/O from
   the bot. Keep Telegram credentials in an environment variable such as
   `TELEGRAM_BOT_TOKEN`; never commit the token or log it.
4. Add a `FeedbackStore` class in its own file. Both interfaces should call the
   same class to save and retrieve feedback. Store feedback separately from the
   original assessment so a correction never overwrites its score or AI result.
5. Give each new assessment a stable ID so feedback reliably points to the
   correct report. The current version-2 reports do not have IDs. Recommended:
   add an ID in a new report schema version, continue reading existing
   version-2 and legacy reports, and define what the UI does when a user tries
   to review an older report without an ID.
6. Decide whether traces should remain live-only or be stored with new reports.
   If stored, add trace validation and backward-compatible loading to the
   Data Manager; do not silently change the strict version-2 schema.

## Feedback record and flow

Agree on the correction choices before coding. At minimum, each entry should
identify the assessment, record whether the user agrees with the result, and
allow an optional correction/comment. Keep the original report immutable.
Avoid storing the entire message again in `feedback.json`; use the stable
assessment ID and only the feedback fields needed by the project.

The CLI and Telegram flows should collect equivalent feedback and call the same
`FeedbackStore` API. The Telegram adapter should associate feedback with the
Telegram user ID only if the team needs that attribution, and should avoid
collecting extra personal information.

## Suggested file and test map

- New `app/assessment_service.py`: shared assessment orchestration class.
- New `app/feedback_store.py`: feedback persistence class.
- New `app/telegram_bot.py` (or a `telegram` package): Telegram interface
  adapter; keep each class in its own file.
- Update `app/main.py` and `app/io_manager.py` for the CLI service and feedback
  prompts.
- Update `app/data_manager.py` only if the report ID or trace is added to saved
  reports; preserve readers for earlier report versions.
- Add offline tests for feedback validation/persistence, both adapter flows,
  JSON serialization of assessment results, old report compatibility, and the
  unchanged scoring fixtures. Mock Telegram transport and AI calls; tests must
  not require live credentials or network access.

## Definition of done

- CLI and Telegram use the same assessment and feedback services.
- Both interfaces display the same score, priority, reasons, actions, matched
  rule, and trace for a live assessment.
- Feedback is persisted and linked to an assessment without changing its
  original score or result.
- Existing version-2 history remains readable.
- Offline tests pass locally and in Docker, and CI passes.
- The report documents the feedback feature and the Telegram bot as the chosen
  advanced GUI feature.
