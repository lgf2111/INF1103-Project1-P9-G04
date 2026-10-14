# PhishReport submission roadmap

Submission branch: `main`. Deadline: **14 October 2026, 23:59 Singapore time**.
Professor requirements govern compliance. Successful CI and closed issues are not approval.

## Submission gates

| Gate | Status | Evidence and remaining acceptance |
| --- | --- | --- |
| G1 - Approved scope | Verified (team confirmation) | The team confirms topic approval and Initial Details were finalized before coding. No new approval is inferred for material revisions; use the approved statement version for delivery. |
| G2 - Procedural application | Partial | Physical manager functions, procedural/I/O checks and validated new-assessment pipeline pass. Instructor API-scope interpretation for history reads remains unresolved. |
| G3 - Automated tests | Verified | Existing 72-case logic script meets Framework 5.3. Application script contains 12 showcase cases and 556 further regressions after removing redundant checks. 640 tests pass in network-disabled Docker. Exact final-main evidence is in the local audit. |
| G4 - Engineering report | Verified (technical content) | One-page report in team voice; data-state diagram and exception matrix together on page 1, verified in the Google Docs PDF export. Report and statement are delivered separately through the confirmed course route. Final upload is a delivery action, not an additional route-approval question. |
| G5 - Git repository | Partial | Granular contributions and focused PRs retained. Issue #78/PR #79 fixed audit defects; issue #80 covers test simplification and documentation. Teammate review explicitly waived for this session only. Invitations, lab access and member clones need confirmation, not presumed absent. |
| G6 - Docker delivery | Partial | Directory persistence, read-only email mount and container recreation checked here. Every member must verify final main; no evidence supplied. |
| G7 - Integrated application | Partial | Manual/folder/browser, validated AI, policy, recovery and persistence checked. Fresh-model repeatability interpretation remains unresolved; final-main evidence belongs in the local audit. |
| G8 - Demonstration | Partial | Explicit 12-case automated showcase and rehearsal sequence prepared. Team rehearsal/individual explanations remain unverified. The later course demonstration is distinct from repository submission. |

## Architecture and storage

`main.py` coordinates I/O -> AI -> logic -> data. Required functions are physically
in `app/io_manager.py`, `app/ai_manager.py`, `app/logic_manager.py` and
`app/data_manager.py`. Helpers have explicit responsibilities: `ai_prompts.py`,
`email_html.py`, `local_settings.py`, `logging_setup.py`, `web_upload.py`.
No authored classes or dynamic class construction are permitted throughout source
and tests. Existing standard-library objects are used through their APIs.

Every new completed assessment requires schema/source-validated AI findings.
Failed AI checks do not score, save or display a completed result. Valid assessments
whose save fails display a distinct warning. History loads stored results without
a new API call; no exception from the course wording is assumed.

New JSON records contain exactly `schema_version:2`, `channel`, `message`, `result`.
Result contains `score`, `priority`, `reasons`, `checklist`. Supported historical
shapes remain readable without manufacturing absent information. Missing files
start empty. Corrupt/unreadable history is preserved and append refused. Duplicate
stored fields and nonfinite scores are rejected. Settings updates are atomic and
preserve corrupt files on failure. Concurrent writers are outside single-process scope.

Docker mounts `.phishreport-data/` at `/data` and an email folder read-only at
`/emails`. Host Python uses its working directory, a separate default history.
Directory mounting permits atomic replacement and recreation preserves data.
Personal state, credentials and `.local/` are excluded from Git and the image.

## Agreed first-match rules

| Condition | Score | Priority |
| --- | --- | --- |
| Password/OTP disclosure | 90 | HIGH |
| AI suspicious and click/download | 80 | HIGH |
| AI suspicious and AI credential request | 60 | MEDIUM |
| AI suspicious | 45 | MEDIUM |
| AI credential request | 40 | MEDIUM |
| Click/download | 35 | MEDIUM |
| AI insufficient context | 20 | LOW |
| Otherwise | 10 | LOW |

HIGH starts at 70 and MEDIUM at 35. Every row requires valid AI first. Scores are
response policy; LOW does not establish safety. Source matching does not prove
extraction completeness or detection accuracy. Attachments/images, PDF input,
live mailboxes and sender authentication are outside implemented scope.

## Tests and cleanup

Only two runnable test scripts remain: `tests/test_logic_manager.py` and
`tests/test_application.py`. Meaningful regressions were consolidated by area,
not discarded as debugging material. The application script's `-m demo` selection
uses real public emails with mocked external AI HTTP, actual local HTTP upload,
exposure, uncertainty, failures and process reload. It does not replace a live
provider demonstration or team rehearsal. Exact commands are in README.

The test review removed 30 redundant functions and unnecessary parameter cross
products (100 collected cases); distinct failure boundaries remain covered. The
logic script is unchanged. `conftest.py` supplies shared imports and registers the
explicit marker; it is test configuration, not a third runnable testing script.

Three pinned real emails in `tests/fixtures/` are necessary offline dependencies;
original bytes and provenance are retained. Unnecessary demo copies and the obsolete
import-review handoff were removed. `emails/` holds local imports only. Hardcoded
AI findings and small malformed protocol/type probes remain test code.

## Team standards and task instructions

Use `<type>/<issue-number>-<short-description>` branches and descriptive
`<type>(<scope>): <action>` commits. Separate behavior, tests, dependencies and
documentation; retain original authorship and granular history. Open focused PRs
to `main`, link issues, obtain a non-author review and resolve comments before merge.
CI is not human approval. Do not force-push shared history. CI runs Ruff,
tracked-Python class checks, pytest, Docker build and network-disabled Docker tests.

## Remaining ordered work

1. Clarify Framework p2 sections 2.2/2.4 and p3 C2/C4: does history retrieval require
   a new API call, and what sameness is expected from fresh AI assessments?
   [PR #25](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/25) leaves
   history scope unchecked. [Issue #32](https://github.com/lgf2111/INF1103-Project1-P9-G04/issues/32)
   and [PR #37](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/37) implement
   temperature zero but contain no instructor interpretation. Both questions remain
   approval blockers pending team/instructor confirmation; no exemption is assumed.
2. Freeze final main, verify its exact commit/CI and rerun affected checks if it changes.
   The audit-session review exception does not waive future teammate reviews.
3. Confirm invitations/lab-in-charge access and member clones. Every member builds,
   tests and runs the same final main in Docker, recording save/restart evidence.
4. Complete the reviewed local temporary-file cleanup in the private action list.
   No new ignore patterns replace deletion. Current documents and personal data stay.
5. Deliver the repository and separate report/approved statement through the confirmed
   course route before the deadline; retain receipts and the submitted commit identity.
   Topic approval and prior Initial Details completion are already team-confirmed.
6. Rehearse the submitted version and each member's contribution explanation for
   the later demonstration. Do not label a prepared sequence a completed rehearsal.

FEATURES.md and original Git/PR records retain contributions. The complete matrix,
verification evidence and private delivery checks are in the local audit. Optional
feature expansion does not take priority over these gates.
