# For Implementation: Feedback Store and Correction Workflow

## Purpose and assignment fit

The feedback workflow is the project's meaningful new feature: users can flag an assessment as incorrect and attach a correction. The Telegram bot remains the selected GUI. Feedback is stored for later human review; it does not change a score or retrain the AI.

## Current branch and status

- Work is on `feat/feedback-store`; the existing branch history is retained.
- The branch includes a merge of the current `origin/main` available when this work began.
- Assessment IDs, feedback persistence, CLI collection, Telegram callbacks, and offline tests are implemented.
- Changes are committed in incremental commits. Nothing has been pushed by this work.

## Current implementation

- `phishreport/feedback/feedback.py` defines the immutable `Feedback` value object and validates feedback categories, optional comments, corrected priority, and the assessment context.
- `phishreport/feedback/store.py` persists feedback separately in an atomic JSON file. It stores the assessment ID and snapshot fields (score, priority, reasons, and matched rule when available), without copying the original message into the feedback record.
- `phishreport/feedback/service.py` creates and validates feedback submissions against the assessment result.
- `phishreport/assessment.py` assigns each assessment a stable ID and saves new reports as schema version 3. `phishreport/data/validator.py` keeps older v1/v2 reports readable and validates v3 reports, including optional rule trace fields when provided.
- `phishreport/io/manager.py` collects an optional CLI category, corrected priority, and comment. `phishreport/cli/main.py` submits these through the shared `FeedbackService`.
- `phishreport/bot/feedback_ui.py` builds Telegram inline keyboards. `phishreport/bot/handlers.py` handles category, corrected-priority, comment, and submit/cancel steps for private chats. The correction button appears only after the report is saved.
- `phishreport/bot/monitor.py` also puts a correction button on a saved Gmail phishing alert.
- Both interfaces use `PHISHREPORT_FEEDBACK_PATH`; the default file is `feedback.json` and is ignored by Git.

## User flow

1. The user receives the completed assessment and can choose a feedback category.
2. For an incorrect priority, the user selects the corrected priority.
3. The user may send a short comment or submit without one.
4. The system stores the feedback linked to the saved assessment. The original assessment remains unchanged.

Supported categories are false positive, false negative, incorrect priority, incorrect explanation, application bug, usability issue, and other.

## Scope and remaining review

- Feedback records retain assessment priority and context for later review. A separate feedback-urgency ranking or review queue has not been defined, so none is inferred here.
- Feedback does not re-score or overwrite prior reports. Reports without a v3 assessment ID cannot start this linked workflow.
- Before merging, run the repository Ruff command and regression suite in the project's supported CI environment. On Windows, `tests/bot/test_gmail.py::test_store_keeps_the_password_private_and_round_trips` checks POSIX permission bits and can fail because Windows does not expose those bits the same way; Linux CI is the authoritative environment for that assertion.
- Update the final project report to describe feedback review/correction as the meaningful feature and the Telegram bot as the GUI/advanced feature.
