# PhishReport submission roadmap

I submit from `main` by 14 October 2026, 23:59 Singapore time. This replaces
outdated planning snapshots; Git and FEATURES.md retain contribution history.
Professor requirements govern compliance. Optional team features are separate.

## General progress and deliverables

| Area | Current position | Evidence / remaining gate |
| --- | --- | --- |
| Input and output | Manual Email/SMS/Chat, common folder/browser .eml parser, exposure questions and explained displays implemented | PRs 19/22/23/39/59/68; real-corpus parity checked |
| AI | Required prompt/API/parse/schema functions, source validation and bounded retry implemented | AI must succeed before every new completed assessment; no fabricated fallback |
| Logic | Agreed eight-rule policy and 35/70 thresholds implemented | PR 64; hardcoded-AI offline tests include the two-AI-field rule |
| Data | Local-only version-2 JSON, atomic append, supported-history validation and recovery | PR 69 plus merged recovery PR 72; no shared database required |
| Docker | Persistent directory, read-only /emails, host upload port, Git Bash paths and LF | PR 67; actual import/save/restart checked here; all-member evidence still required |
| Required filenames | Four actual app/*_manager.py files with physical function definitions | Issue 71; structural and full runtime tests pass on code f8dbf4e |
| Report and scope | Engineering report and Initial Details are maintained locally | Report five pages, diagram/matrix page 2; approval remains unverified |
| Delivery/demo | Main designated; checklist and rehearsal steps prepared | Team confirmations, rehearsal and course receipt still needed |

## Project structure and architecture

The pipeline is I/O -> AI -> logic -> data, coordinated by main.py. All direct
terminal calls live in io_manager.py. AI contains transport/validation; logic
contains domain rules; data contains local JSON operations. Required functions
are physically defined in the four named files. Explicitly named app-level helpers do not
replace those managers. No authored classes or dynamic class constructors are allowed.

New storage has exactly schema_version:2, channel, message and result. Result
contains score, priority, reasons and checklist. Supported historical formats
are validated without manufacturing absent fields. Corrupt history is preserved.

## Agreed decision rules

| First match | Score | Priority |
| --- | --- | --- |
| Password/OTP disclosure | 90 | HIGH |
| AI suspicious and click/download | 80 | HIGH |
| AI suspicious and credential request | 60 | MEDIUM |
| AI suspicious | 45 | MEDIUM |
| AI credential request | 40 | MEDIUM |
| Click/download | 35 | MEDIUM |
| AI insufficient context | 20 | LOW |
| Otherwise | 10 | LOW |

Every row requires valid AI findings first. Scores express response policy,
not probability. HIGH starts at 70 and MEDIUM at 35. LOW does not establish safety.

## Team standards and task instructions

I use `<type>/<issue-number>-<short-description>` branches and
`<type>(<scope>): <action>` commits. Each issue states the bug, affected contract,
acceptance checks and PR. I commit coherent tested blocks, preserve contributor
history and keep structural changes separate from behavior fixes. I reproduce
observed failures before fixing them and request review from affected teammates.

I open focused PRs to main, link issues and record exact-head checks. I seek a
non-author review and resolve comments; CI success does not imply human approval.
I preserve granular commits with merge commits rather than squashing the lifecycle.
I never force-push shared history routinely. Repository protection rules apply.

CI runs Ruff, tracked-Python class checks, pytest and Docker build/tests.
Mandatory manager/I/O/procedural checks also run as offline tests. I distinguish
live AI, recorded-response replay and hardcoded unit tests in verification claims.
Each member still needs to run the final submission commit inside Docker.

## Outstanding decisions and optional work

I need instructor interpretation of fresh-model repeatability and whether reading
saved results requires another API call. Temperature zero and successful samples
do not establish universal determinism. No caching exception is assumed.

Topic approval, Initial Details receipt, repository invitations/clones and the
course submission receipt need confirmation. A rewritten statement is not approval.

Open UX proposals such as categorisation and automatic metadata extraction are
optional. Filtering, report status, accounts, image/PDF analysis, attachment
execution and mailbox integration are outside required Phase 1 closure. User
clicks/downloads/disclosure cannot be inferred from message text.

## Submission readiness checklist

I tick a gate only after its final-main evidence is recorded. My local release checklist includes real-email and demo steps.

- [ ] **G1 - Approved scope:** current statement exists; instructor sign-off unverified.
- [ ] **G2 - Procedural application:** physical files/functions, I/O, AI and validation
  checked locally; final-main verification and AI-scope clarification remain.
- [ ] **G3 - Automated tests:** 694 offline Docker tests passed on code f8dbf4e;
  rerun/confirm on the integrated submission commit.
- [ ] **G4 - Engineering report:** current five-page PDF prepared; confirm the required delivery route.
- [ ] **G5 - Git repository:** focused history and PRs exist; access, clones, Initial
  Details submission and final-head CI evidence must be recorded.
- [ ] **G6 - Docker delivery:** saving/restart verified here; every member must verify.
- [ ] **G7 - Integrated app:** real .eml import/upload/save/restart and failures checked;
  final-main checks and repeatability interpretation remain.
- [ ] **G8 - Demonstration:** steps prepared; rehearsal and individual explanations needed.

## References

Team Project Framework - Phase 1, sections 1-5; Team Project Specification,
pp 15-16; Project Initial Details, pp 1-2; Grading Criteria1, p 1. Course PDFs
and submission documents are maintained locally. README.md explains setup.
