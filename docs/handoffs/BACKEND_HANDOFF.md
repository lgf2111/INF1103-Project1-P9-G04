# Backend handoff for Telegram

The CLI and Telegram launchers compose shared Python managers in their own
processes. This is an in-process API, with no HTTP backend. The
[Telegram run guide](../../README.md#telegram-bot) covers setup, exposure questions
and the isolated-history demo. `/start`, connection checks and Gmail commands
remain available; saved-report browsing and summaries use the CLI.

## Implemented assessment boundary

`phishreport.assessment.AssessmentService` accepts record dictionaries containing
`channel`, `sender`, `message`, `has_link`, `link`, `has_file`, `file_name`,
`clicked`, `downloaded`, and `submitted_category`. The shared logic validates the
input and AI findings. `ChatRecordBuilder.build(text, sender=None)` creates a
`chat` record and preserves the original message. It extracts the first supported
HTTP/HTTPS/www URL and filename clue, excluding filenames inside URLs/email
addresses. An attachment mention may give `has_file=True`, `file_name=None`.
These are textual clues: no URL is fetched, no attachment is inspected, and no
interaction is inferred. The current Telegram handler calls the builder without
a sender. Initial scoring uses false interaction flags while session answers
remain explicitly unknown.

- `assess(record) -> dict`: existing one-AI-call assessment used by CLI/Gmail.
- `assess_with_findings(record) -> AssessmentSnapshot`: one AI call; returns
  independent `findings` and `result` dictionaries, retaining findings for Telegram.
- `rescore(record, findings) -> dict`: logic only, with independent working copies;
  explicit retained findings replace any stale `record["ai"]`. No AI call.
- `build_report(record, result) -> dict`: constructs the four-field v2 report
  (`schema_version`, `channel`, `message`, `result`) used by CLI/Gmail.
- `build_exposure_report(record, result, exposure) -> dict`: constructs an
  independent v3 report, selecting only the fields below. It performs no scoring
  or validation; `DataManager.save` validates before writing.

Here, one AI call means one initial AIManager assessment operation; existing
provider retries/fallback may make multiple HTTP attempts. Answer changes and
completed-save retries do not request fresh findings.

A result has exactly `score` (integer 0–100), `priority` (`LOW`, `MEDIUM`, `HIGH`),
`reasons` and `checklist` (lists of nonblank strings, which may be empty). Scores
are response priorities, not probabilities. Valid AI findings are required even
when the user reports disclosure; findings are not bypassed to manufacture HIGH.

## Completed v3 report

This JSON example shows the exact ten top-level fields and four exposure fields:

```json
{
  "schema_version": 3,
  "channel": "chat",
  "message": "Please verify at https://example.test/account",
  "result": {
    "score": 80,
    "priority": "HIGH",
    "reasons": ["Suspicious message with a reported link click."],
    "checklist": ["Contact the organisation through a known official channel."]
  },
  "sender": null,
  "has_link": true,
  "link": "https://example.test/account",
  "has_file": false,
  "file_name": null,
  "exposure": {
    "clicked": true,
    "downloaded": false,
    "submitted_category": null,
    "disclosure_answered": false
  }
}
```

`clicked` and `downloaded` are boolean or `null`: null means unanswered, false
means explicitly no. `submitted_category` is `null`, `"password"` or `"otp"`.
Null plus `disclosure_answered=false` is unknown; null plus true is confirmed no
disclosure. A category with false is invalid. `has_link` must agree with a
non-null link; a non-null filename requires `has_file=true`, while a generic file
mention may have no filename. The v3 validator rejects extra/missing fields,
invalid types and inconsistent combinations without changing the report.

Only confirmed True values project into scoring and exposure counts. Unanswered
fields display **Unconfirmed**, and any unanswered question adds **Exposure
unconfirmed**. Cached AI findings are not persisted. `ReportValidator` accepts
new v2/v3 reports and loads supported unversioned, v1, v2 and v3 history without
reassessing or rewriting it. CLI history/presentation and summaries understand v3; existing
CLI/Gmail assessment output remains v2.

## Telegram lifecycle and callback ownership

The initial reply is provisional and unsaved. One keyboard presents interaction
choices **Clicked link**, **Downloaded file**, **Both**, **Neither** and disclosure
choices **Password**, **One-time code**, **Neither password nor code**. Answer
changes rescore retained findings only. **Finish and save** and **Skip unanswered**
both freeze the current answers/result, preserving partial answers and unknowns.
Only finalization writes. A failed write leaves the completed snapshot available
for **Retry saving**, without another AI call. Success is announced only after
storage confirms it; a later Telegram edit failure does not undo saved state.

`ExposureSession` binds an opaque token to originating chat/user/message IDs.
Callbacks must also match the bot's question-reply message ID. The handler parses
only the `exposure:<token>:<action>` namespace, acknowledges first, then checks
private-chat authorization, token and ownership. Source delivery deduplication
uses `(chat, user, message)` while cached; distinct source messages with identical
text remain distinct assessments. Failed reply delivery retains its snapshot for
redelivery without another AI call.

Unfinished sessions expire after 30 minutes using monotonic time and lazy cleanup,
or disappear unsaved on restart. Completed unsaved reports survive the pending
timeout while the process lives. The cache limit is 1000 sessions: new sources may
evict old unlocked saved sessions, but active pending, locked and completed
unsaved sessions are retained; full active capacity returns a busy reply before
AI work. Saved sessions can expire too, so replay protection lasts only while
state is retained. Restart loses in-memory state, including unsaved completions.

Message and exposure callback registrations use `block=False`, without changing
global update concurrency or Gmail ordering. AI/storage run off the event loop;
handlers never await a future answer. The initial-message lock serializes source
assessment/delivery separately from callback saves. A per-session lock serializes
answer changes/finalization and rendering. The save helper owns that lock; callers
must not already hold it. The shared save lock also serializes Gmail report writes.
Cancellation while waiting for the save lock starts no write; after a write starts,
the helper shields/waits for its outcome while retaining locks and records success
before propagating cancellation. Process termination cannot guarantee this outcome.
Repeated finalization uses the cached report and saved flag; this is in-process
deduplication, not durable distributed exactly-once delivery.

### Implemented report storage

`phishreport.data.ReportStorage` is the shared storage ABC. `JsonReportStorage`
and `SqliteReportStorage` implement ordered replacement and fresh, independently
mutable reads. Missing files read as `[]`; malformed stored contents raise
`ValueError`, and operational I/O failures raise `OSError`. `DataManager`
continues to validate report schemas and expose save/load/query operations.

Both launchers call `phishreport.data.factory.create_report_storage()` during
composition. Set `PHISHREPORT_STORAGE=json|sqlite` in the process environment;
the default is JSON. `PHISHREPORT_REPORTS_PATH` defaults to `reports.json` locally
and `/data/reports.json` in the Telegram image. SQLite uses the sibling path with
a `.sqlite3` suffix. The CLI loads `.env` after composition, so local storage
selection must be exported in the shell. Docker `--env-file .env` works because
it sets the process environment before the launcher runs.

SQLite stores strict JSON payloads in
`records(position INTEGER PRIMARY KEY, payload TEXT)`. Each operation owns and
closes its connection. Writes use WAL, a five-second busy timeout, and an atomic
replacement transaction. DataManager's read/modify/write sequence remains a
single-writer contract; use the bot's existing shared save lock for bot writers.

For migration, stop application writers and call
`phishreport.data.migration.migrate_json_to_sqlite(source, target)`. It requires
an existing valid JSON source and distinct destination, preserves source bytes
and legitimate duplicates, and returns the imported record count. Identical
reruns return `0`; different nonempty destination history is refused. Switching
the environment selector alone does not migrate records.

The whole `/data` directory must be mounted writable for the database and its
WAL/SHM files. The [README storage instructions](../../README.md#report-storage-and-migration)
include local and container migration commands. The shared fixture in
`tests/core/test_data_core.py` is parametrized over both production backends.
Run it alongside `test_sqlite_storage.py`, `test_storage_factory.py` and
`test_storage_migration.py`; all live AI/Telegram access is mocked. Observe a real
offline Docker run and unprivileged POSIX permission checks before recording
those checks as passed.

## Actual errors and input limits

The service propagates standard exceptions: `ValueError` for invalid input or
AI output, `RuntimeError` when the AI cannot complete, and `OSError` for storage
operations. It defines no typed error-code protocol. AI failures produce no
snapshot or fallback LOW result. Telegram translates provider RuntimeErrors with
`AIErrorTranslator`; initial ValueErrors produce a failed-check reply. Callback
ValueError/RuntimeError/OSError receive generic update/retry wording, with the
completed-unsaved formatter showing Retry saving after a failed write.
`DataManager.load(strict=True)` propagates read/validation failures; default
`tolerant` load logs a fixed diagnostic and returns `[]`. Saving validates the new
report and entire strict history before replacement, propagating failures.

The shared message-text limit is 50,000 characters. CLI `.eml` imports are limited
to 2 MiB and parse supported text/HTML content, not attachments or embedded images.
Those import paths and Gmail monitoring are independent of Telegram's text
exposure-question flow.

## Reproducible checks and remaining evidence

Use the focused offline commands and isolated JSON/SQLite demo in the
[README](../../README.md#check-the-exposure-flow-with-an-isolated-history).
Offline fixtures mock AI/Telegram; actual `Application.process_update` tests
exercise dispatch while AI or callback storage is paused. They do not establish
live provider behavior, a mounted restart, or a remote CI pass.

The existing Telegram-image offline command uses `--network none`,
`--user 65534:65534`, `--workdir /tmp` and pytest `--rootdir=/app`; see the
[container instructions](../../README.md#run-docker-with-persistent-reports).
CI/Docker currently use Python 3.14 while the local target is 3.12. Docker and
`gh` were unavailable and WSL was not installed at this documentation checkpoint;
no local container or matching remote CI result was observed. Record an observed
CI run for the matching pushed revision separately. The prior local full suite
reported 1630 passed, 18 skipped and the unchanged Windows Gmail `0600` versus
`0666` permission assertion failure; do not treat it as a clean pass.
