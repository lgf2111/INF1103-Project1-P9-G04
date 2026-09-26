# PhishReport Project Roadmap 2.0

> **Draft for team review.** The structure and workflow are ready to propose; team adoption and optional features are still pending.
>
> **Progress reviewed:** 27 September 2026 — `main` at `aa5db66`, input branch at `e730274`, extraction branch at `613d4fb`.

## Contents

1. [General progress and deliverables](#general-progress-and-deliverables)
2. Four-layer architecture
   1. [Input Layer](#input-layer)
   2. [AI Processing Layer](#ai-processing-layer)
   3. [Logic Layer](#logic-layer)
   4. [Data Layer](#data-layer)
3. [Project structure and architecture](#project-structure-and-architecture)
4. [Team standards and task instructions](#team-standards-and-task-instructions)
   1. [Code rules and automatic checks](#code-rules-and-automatic-checks)
   2. [Task instructions](#task-instructions)
   3. [How we work together (Git)](#how-we-work-together-git)
   4. [Shared changes and completion](#shared-changes-and-completion)
   5. [Standards rollout](#standards-rollout)
5. [Outstanding decisions](#outstanding-decisions)
6. [References](#references)
7. [Submission readiness checklist](#submission-readiness-checklist)

## General progress and deliverables

**Objective:** Assess suspicious email, SMS and chat messages with a procedural Python CLI. Use AI findings and phishing rules to produce prioritised JSON reports.

**Current stage:** Week 5 — agree contracts, refactor and integrate the layers. Prepare for Week 7 submission and the Week 8 demonstration.

**Status key**

- **Implemented:** Present on `main`.
- **Branch work:** Unmerged implementation.
- **Partial:** Some acceptance criteria remain.
- **Pending:** No completion evidence yet.

Check a deliverable only when its acceptance criteria pass on the submission version; record evidence in its issue or PR.

### Project progress

| Area | Status | Current position |
| --- | --- | --- |
| Core pipeline | Implemented | Four procedural managers and `main.py` connect input, AI, assessment, display and JSON storage. |
| Input extension | Branch work | Menu validation and channel/sender/link/file helpers in PR #14; new helpers still need integration. |
| AI extraction extension | Branch work | Email, phone and IP extraction, validation and a second AI response on `feat/xh-logic-manager`. |
| Assessment rules | Partial | Five outcomes, fixed scores and checklists exist; two-AI-field rule and exposure/uncertainty cases remain. |
| Report history | Partial | Save/load/query and basic listing exist; menu filtering, startup loading and status updates remain. |
| Tests and CI | Implemented | 24 offline tests on `main`; Ruff, source no-class check, tests and Docker build/tests configured. |
| Docker and release | Partial | Dockerfile, helper and v1.0.0 release exist; persistent report storage and all-laptop verification remain. |
| Foundation and standards | Pending | Keep the existing `app/` layout. Team adoption of the workflow and branch protection are unverified. |
| Submission documents | Pending | Final engineering report and submission-version verification evidence remain. |

### Remaining schedule

| Checkpoint | PhishReport deliverable |
| --- | --- |
| Week 5 — proposed team target | Finalise contracts and rules; adopt standards; refactor and integrate layer work. |
| Week 6 — proposed team target | Complete features, failure tests, repeatability checks, report and all-laptop Docker verification. |
| Week 7 | Source code, engineering report, automated test script, Git repository history and Docker delivery. |
| Week 8 | Demonstration of the submitted application. |

### General deliverables

- **G1 — Problem, users and measurable scope · Pending**
  - Record instructor topic sign-off and the required one-paragraph problem statement.
  - State target users, their problem, supported channels/actions and exclusions in README and the report. Explain the value over unaided checking.
  - Define success scenarios and expected outcomes in `docs/design.md`.
- **G2 — Procedural application · Partial**
  - Keep four functional managers and no team-authored classes; confine `input()` and `print()` to I/O.
  - Send every processed record through the real API. Validate AI findings before use and make them drive assessment.
  - Clarify how the API rule applies to operations on existing records.
- **G3 — Automated tests · Partial**
  - Test `evaluate`, `score`, `route` and a rule combining at least two AI-response fields with offline fixtures. Pass inside Docker.
- **G4 — Engineering report · Pending**
  - Keep the report within five pages. Put the data-flow diagram and exception-handling matrix on one page.
  - Cover API failure, malformed response, missing/corrupt data and invalid input.
- **G5 — Git repository · Partial**
  - Show granular descriptive commits, task branches and reviewed PRs. Verify the submission URL and access for all members and lab-in-charges.
  - Confirm the Project Initial Details file was committed and submitted through the required channel.
- **G6 — Docker delivery · Partial**
  - Provide a root Dockerfile and working output from the submission branch; install dependencies inside the container.
  - Have all six members verify it locally. Record member, commit, command, date and result for each laptop.
- **G7 — Integrated app verification · Pending**
  - Pass normal, exposure, uncertain, API-failure, save/restart/retrieve and priority-filter cases.
  - Keep container reports across runs; pass D5 repeatability against the recorded instructor interpretation.
- **G8 — Demonstration · Pending**
  - Rehearse the full pipeline, failures and offline tests. Every member explains their contribution and the system.

### Requirement labels and proposed scope

**Course requirements**

- Four functional managers; input type/range validation; structured AI responses and rules combining AI fields.
- Numeric scoring used for ranking or thresholds; JSON/CSV persistence and repeatability.
- Offline tests, an engineering report, meaningful Git history and Docker delivery.

**Instant-fail constraints**

1. No team-authored class definitions.
2. Every processed record passes through the AI API; the application's main purpose depends on AI.

Whether viewing, filtering or updating existing records requires another call needs instructor clarification. Do not assume an exemption or use caching to bypass the requirement.

**Team proposals, not professor-mandated features**

- Email/phone/IP extraction (A2/L5) and a second AI formatting call (A3).
- Handled/ignored report status (I4/D3) and exact issue/commit/review/merge conventions.

Complete the mandatory assessment flow before optional extensions. Record retained proposals in `docs/design.md`.

**Phase 1 exclusions:** Inbox integration, automatic monitoring, opening links or attachments, and claims that a message is guaranteed safe.

**Proposed users:** Non-specialist students and staff checking suspicious email, SMS or chat messages.

**Problem:** Users need help interpreting phishing indicators and choosing actions after clicking, downloading or disclosing information.

**Expected value:** Combine AI interpretation with reported user actions to produce a consistent priority, reasons, response checklist and saved history. Do not claim proven superiority or guaranteed safety.

**Measurable objectives**

- Define fictional normal, suspicious, exposure and insufficient-context cases with expected decisions.
- Pass every agreed rule case; reject malformed AI output without a successful assessment.
- Retrieve unchanged saved assessments after restart. Record exclusions and evaluation results in the report.

### Implementation sequence

- [ ] Agree schemas, interfaces, rule table and ownership of individual tasks in `docs/design.md` and GitHub issues.
- [ ] Preserve existing tests, DevOps configuration and useful branch work; separate file moves from feature changes.
- [ ] Keep the agreed `app/` layout; verify imports, test discovery, Docker, CI and README commands against it.
- [ ] Integrate input helpers and any retained extraction fields without removing phishing assessment.
- [ ] Complete each layer's deliverables and cross-layer tests.
- [ ] Verify the submission commit against G1-G8; record member checks and submit.

## Input Layer

### In charge: Jeremy & Bryan

**Purpose:** Collect structured message details and reported user actions. Display assessments, reports, lists and errors.

**Boundary:** All terminal input/output belongs in `io_manager.py`.

### Features and progress

| Feature | Status | Scope |
| --- | --- | --- |
| Main menu | Implemented / branch extension | Check message, view reports and quit; PR #14 adds re-prompting inside the menu function. |
| Message validation | Implemented / branch extension | Reject blank messages; branch adds a reusable `get_message()`. |
| Yes/no validation | Implemented / branch extension | Main accepts `y/n`; branch accepts `yes/y/no/n` case-insensitively. |
| Channel | Branch work | `get_channel()` validates Email, SMS or Chat. |
| Sender | Branch work | `get_sender()` accepts optional sender information and returns `None` when blank. |
| Included link/file | Branch work | `get_link_information()` and `get_file_information()` collect presence plus a nonblank URL/file name. |
| User actions | Implemented | Collect clicked, downloaded and submitted category (`password`, `otp` or none). |
| Results and history | Partial | Priority, score, checklist and short report list exist; full record display, filter controls and status controls remain. |

**Source:** [PR #14](https://github.com/lgf2111/phish-report/pull/14). Channel, sender, link and file helpers exist but are not called by `collect_input()`.

### Deliverables

- [ ] **I1 — Complete input record**
  - Connect helpers to `collect_input()`. Return channel, optional sender, message, included-link/file details and user actions in the agreed dictionary.
  - Convert flags to booleans and choices to agreed values.
- [ ] **I2 — Input validation**
  - Define applicable ranges and length limits in `docs/design.md`. Re-prompt for invalid types, ranges, choices, required values and inconsistent actions.
  - Test each agreed boundary and adjacent invalid value. The course does not prescribe numeric limits.
  - Distinguish receiving a link/file from clicking/downloading it. Collect disclosure categories, never actual passwords or OTPs.
- [ ] **I3 — Displays**
  - Implement `display_record`, `display_list` and `display_result` with reasons, score, priority, checklist and agreed extracted details.
  - Display failures through the I/O layer.
- [ ] **I4 — History controls**
  - Add report selection and priority filtering.
  - Add handled/ignored controls only if adopted with agreed values and transitions.
- [ ] **I5 — Tests and integration**
  - Test menu choices, case/whitespace handling, blanks, optional fields, links/files and complete returned records.
  - Keep all application `input()` and `print()` calls in this module.

## AI Processing Layer

### In charge: Arvin & Guan Feng

**Purpose:** Send processed records through the real AI API; build prompts, parse JSON and validate findings before the logic layer uses them.

**Boundary:** Keep phishing decisions and scoring outside `ai_manager.py`. Clarify API rules for viewing, filtering and updating existing records before implementing those operations.

### Features and progress

| Feature | Status | Scope |
| --- | --- | --- |
| API access | Implemented | Groq chat-completions request, JSON response mode, environment key, model setting and 30-second timeout. Current default model: `openai/gpt-oss-20b`. |
| Phishing findings | Implemented | `build_prompt`, `call_api`, `parse_response`, `validate_response`; boolean `credential_request`, `suspicious`, `insufficient_context`. |
| Response parsing | Implemented | Parse JSON and supported Markdown code fences; check required keys and boolean values. |
| Contact/IP extraction | Branch work | Extract email addresses, eight-digit phone numbers including `8000 1234`, and IPv4/IPv6 addresses. Preserve order, duplicates and original text. |
| Extraction validation | Branch work | Validate exact object keys, list/string types, formats and ordered source occurrences; reject invented values. Existing validation does not prove every occurrence was extracted. |
| Final AI response | Branch work | Second API call formats `Email: ..., Phone Number: ..., IP Address: ...`; validates labels, order and exact values. |
| Failure handling | Partial | Missing key, connection errors and timeouts report failure; malformed response envelopes, logging and retry policy remain. |

**Source:** [`feat/xh-logic-manager`](https://github.com/lgf2111/phish-report/tree/feat/xh-logic-manager). Port its AI work into this layer's backlog. The extraction-only flow is a prototype; integration must retain phishing findings and the required manager functions.

### Deliverables

- [ ] **A1 — Shared schema and prompts**
  - Define phishing findings and any retained extraction fields in `docs/design.md`.
  - Keep `build_prompt`, `call_api`, `parse_response` and `validate_response` public; map prototype helpers into that interface.
- [ ] **A2 — Proposed extraction integration**
  - If adopted, integrate email/phone/IP extraction, validation and completeness checks.
  - Test absent categories, repeats, order, hyphenated emails, spaced phones, IP labels and invalid source matches.
- [ ] **A3 — Proposed second AI call**
  - Decide whether to retain the formatting call. If retained, validate and display its output alongside the procedural assessment.
- [ ] **A4 — Robust failures**
  - Reject non-object JSON, missing fields, wrong types, invalid values and malformed API envelopes.
  - Log failures, return agreed failure information and bound retries under an explicit policy. Never save a failed call as a completed assessment.
- [ ] **A5 — Configuration**
  - Read the chosen model after environment loading. Document key/model setup, timeout, retry limit and verified provider access.
- [ ] **A6 — Verification**
  - Add offline API mocks and schema/error tests.
  - Record a successful live request using fictional input and a complete assessment through all managers.

## Logic Layer

### In charge: Bryan & Xavier

**Purpose:** Combine validated AI findings and reported actions into an assessment, score, outcome and response checklist.

**Boundary:** Keep API requests, terminal interaction and file access outside `logic_manager.py`.

### Features and progress

| Feature | Status | Scope |
| --- | --- | --- |
| Evaluation | Implemented | `evaluate(record)` returns priority, score and checklist. |
| Routing | Implemented | `route(record)` selects high, medium, review, insufficient information or no clear indicators. |
| Scoring | Partial | `score(record)` maps the route to 90/70/50/30/10; scoring must be used for ranking or thresholds. |
| Checklists | Implemented | Each outcome has actions; no-clear-indicators text does not claim guaranteed safety. |
| Rule using two AI fields | Pending | Current rules combine one AI field with user action, not two AI-response fields. |
| Exposure and uncertainty | Pending | Define credentials submitted without an AI credential finding, suspicious content with insufficient context, and personal-information/payment cases. |
| Extracted-details handoff | Branch work | `hold_details(details)` preserves extracted data unchanged; branch removes the current assessment functions. |

**Source:** [main logic manager](https://github.com/lgf2111/phish-report/blob/aa5db66/app/logic_manager.py) and [`feat/xh-logic-manager`](https://github.com/lgf2111/phish-report/tree/feat/xh-logic-manager). Retain useful extraction handoff work within a complete assessment flow; a pass-through alone does not complete this layer.

### Deliverables

- [ ] **L1 — Decision table**
  - Specify inputs, AI fields, conditions, precedence, outcome and checklist for every rule.
  - Include a rule combining at least two named AI-response fields.
- [ ] **L2 — Required functions**
  - Preserve and complete `evaluate`, `score` and `route`.
  - Return a consistent decision dictionary with reasons, score, priority and checklist.
- [ ] **L3 — Numeric scoring**
  - Define score range, calculation and ranking/threshold use. Derive the score from AI findings; call it rule-based, not a probability.
- [ ] **L4 — Exposure and uncertainty**
  - Implement agreed outcomes for reported credential disclosure, clicks/downloads, insufficient context and conflicting findings.
  - Define support for personal information and payments before adding those input choices.
- [ ] **L5 — Proposed extraction compatibility**
  - If retained, pass validated details through evaluation and storage without replacing phishing rules with `hold_details()`.
- [ ] **L6 — Offline tests**
  - Use hardcoded AI responses to test every route, exact score, boundary, precedence, two-AI-field combination, exposure/uncertainty case and checklist.
  - Pass inside Docker without API access.

## Data Layer

### In charge: Bryan & Xavier

**Purpose:** Save and retrieve evaluated JSON reports across runs; support history, filters and any agreed status updates.

**Boundary:** Keep assessment rules and terminal display outside `data_manager.py`.

### Features and progress

| Feature | Status | Scope |
| --- | --- | --- |
| Save | Implemented | `save(record)` appends an evaluated record to `reports.json`. |
| Load | Partial | `load()` reads records and returns `[]` for missing/malformed files; startup integration and loaded-schema validation remain. |
| Query | Implemented | `query(filter_fn)` returns matching records; not connected to a menu filter. |
| Stored assessment | Implemented | Saves user input/actions, validated AI findings and final result. |
| Priority filtering | Planned in FEATURES.md | Connect `query()` to report-history controls. |
| Report status | Planned in FEATURES.md | Support handled/ignored updates after agreeing allowed values and transitions. |
| File failures | Partial | Read errors are caught; warning currently uses `print()` here. Safe writes, corrupt-file preservation and save-error handling remain. |
| Container storage | Pending | Current Docker helper has no persistent mount for reports. |

**Sources:** [data manager](https://github.com/lgf2111/phish-report/blob/aa5db66/app/data_manager.py), [FEATURES.md](https://github.com/lgf2111/phish-report/blob/aa5db66/FEATURES.md). No separate data-layer feature branch was found in the reviewed repository.

### Deliverables

- [ ] **D1 — Record contract**
  - Define identity, input/actions, validated AI findings, retained extracted details, decision and any adopted report status in the saved schema.
  - Keep processing state, priority and user status distinct.
- [ ] **D2 — Persistence and startup**
  - Save only evaluated reports and load records on startup.
  - Return `[]` for missing/corrupt files; report errors through the agreed logging/I/O path.
- [ ] **D3 — Queries and updates**
  - Connect priority filters to `query(filter_fn)`.
  - If adopted, update status by report identity without changing the original assessment.
- [ ] **D4 — Safe file handling**
  - Validate loaded structure and preserve corrupt files before replacement.
  - Handle permission/write failures, prevent partial writes from destroying reports and remove terminal output from this module.
- [ ] **D5 — Compatibility and repeatability**
  - Define handling for existing main-branch reports and retained extraction-prototype records.
  - Record the instructor's interpretation of same input/output, including API-call behaviour.
  - Freeze fictional inputs, configuration and fields to compare. Run them in at least two sessions and compare required outputs exactly.
  - Record commands, submission commit and results. Test saved-record reload separately; reload alone does not prove fresh-assessment repeatability.
- [ ] **D6 — Docker and tests**
  - Configure persistent report storage.
  - Test round trips, append, queries, updates, missing/corrupt/wrong-shape files, write failures and retrieval after container restart.

## Project structure and architecture

**Proposed target:** Keep the existing application layout and useful configuration, tests and contribution history. Create new files only when they contain required content.

```text
phish-report/
|-- README.md
|-- ROADMAP.md
|-- LICENSE
|-- .env.example
|-- .gitignore
|-- .dockerignore               # Add
|-- Dockerfile
|-- docker.sh
|-- requirements.txt
|-- ruff.toml
|-- conftest.py
|-- app/
|   |-- main.py
|   |-- io_manager.py
|   |-- ai_manager.py
|   |-- logic_manager.py
|   `-- data_manager.py
|-- tests/                      # Preserve existing tests; extend by layer
|-- docs/
|   |-- design.md               # Schemas, interfaces, rules and failure contracts
|   `-- report/                 # Engineering report and diagrams
|-- .local/                     # Ignored: draft roadmap and local course PDFs
`-- .github/
    `-- workflows/
        |-- ci.yml
        `-- release.yml
```

Retain `FEATURES.md` as contribution history or move its records to a documented location during migration. Keep the existing licence. Exclude secrets, `.env`, environments, caches, logs and user reports from Git and Docker build context.

```text
Input Layer -> AI Processing Layer -> Logic Layer -> Data Layer
                    main.py coordinates; Input Layer displays results
```

| Boundary | Required contract |
| --- | --- |
| Input -> AI | Validated dictionary with explicit field names, types and allowed values. |
| AI -> Logic | Schema-validated findings and agreed extracted details, or a defined failure result. |
| Logic -> Data | Evaluated record with decision, score, route and checklist. |
| Managers -> I/O | Structured results/errors; only I/O prompts or prints. |

Use functions and dictionaries; no team-authored class definitions in source or tests. Document signatures, return values and failure behaviour in `docs/design.md`. Keep `main.py` limited to coordination.

Add helpers to the responsible manager unless a distinct responsibility needs its own module. Keep the four required manager files and public functions. Update callers, imports, tests, commands and design notes together; avoid circular imports.

## Team standards and task instructions

**Draft team standards:** Exact issue/commit formats, review counts and merge methods still need team adoption. Descriptive history and focused branches remain course requirements. Give each task one individual owner and one reviewer; layer ownership does not replace task assignments.

### Code rules and automatic checks

GitHub Actions runs these checks on pushes and pull requests:

1. **No classes.** Phase 1 requires functions only. CI currently searches `app/`; the foundation task extends this to all team-authored Python. A found class definition fails the check.
2. **Lint (Ruff).** Flags unused code, import-order problems and other configured issues. Run it locally if installed:

   ```bash
   ruff check .
   ```

3. **Offline tests.** Run `pytest` without a live API key. Update tests when changing rules or other assessed behaviour.
4. **Docker build and tests.** CI builds the image and runs the offline tests inside it. This does not replace the final interactive run on every team laptop.

A green CI result still needs review and submission-version verification.

### Task instructions

Create one GitHub issue per focused task using the relevant roadmap ID.

| Field | Required content |
| --- | --- |
| Title | Layer and concrete action, e.g. `I1: Connect channel and sender input`. |
| Owner / reviewer | One implementer and one reviewer; paired implementers use a third reviewer. |
| Scope | Functions/files to change and the required behaviour. |
| Contract | Input fields/types, output fields/types and error behaviour, or a link to the agreed design section. |
| Dependencies | Blocking task IDs and interface decisions. |
| Acceptance criteria | Observable outcomes, including failure cases. |
| Verification | Tests or reproducible manual steps and expected results. |
| Evidence | PR link, test results and any remaining work. |

Write instructions as **action + expected result**. Use **must** for requirements and **proposed** for unresolved choices. Put explanations and discussion in issue comments; keep the roadmap to scope, status, decisions and acceptance criteria.

Task states: **Backlog -> Ready -> In progress -> In review -> Done**. Move to Ready when scope, contracts and dependencies are settled. Record blockers on the issue. Update the issue and layer checklist when work merges.

### How we work together (Git)

#### Branches and commits

Start each task from current `main`. Use short-lived task branches; do not push directly to `main` or use permanent personal branches.

| Item | Format | Example |
| --- | --- | --- |
| Branch | `<type>/<issue-number>-<short-description>` | `feat/21-input-record` |
| Commit | `<type>(<scope>): <short action>` | `feat(io): collect channel and sender` |

Types: `feat`, `fix`, `test`, `docs`, `refactor`, `ci`, `chore`. Scopes: `io`, `ai`, `logic`, `data`, `app`, `repo`, `build`. Use lowercase branch names, hyphens and real issue numbers.

Commit coherent changes early and often with accurate authorship. Push and sync task branches regularly, including before handoffs and review. Preserve existing contributor history. Separate unrelated work and behaviour changes from structural moves.

#### Pull requests and merging

- Open one focused PR to `main`; link its issue and state changes, verification and outstanding work.
- Obtain one non-author approval. Paired authors require a third reviewer.
- Pass applicable CI checks and resolve review comments. Obtain another review after substantive changes.
- Update local `main` with a fast-forward-only pull. Investigate divergence instead of forcing it.
- Update published/shared branches by merging `origin/main`; resolve conflicts with affected contributors and rerun checks.
- Rebase only exclusively local, unpublished commits that nobody depends on.
- Merge approved PRs using **Create a merge commit**. Do not squash, rebase shared history or force-push routinely.
- After merging, update tracking and delete the completed task branch when no longer needed.

### Shared changes and completion

**Proposed DevOps coordinator: Guan Feng.** Coordinate CI/Docker changes, maintain the all-laptop verification record and flag failed checks. Each member runs the submission version on their own laptop. Confirm this assignment during draft adoption.

Agree contract changes with affected layer owners before implementation. Update producers, consumers, tests and design documentation together. Assign an owner/reviewer explicitly for shared `main.py`, Docker, CI and documentation tasks.

**Done:** Acceptance criteria met; checks passed; independent review complete; merged into `main`; affected documentation and progress updated.

### Standards rollout

- [ ] Team adopts the draft task, naming, review and merge standards.
- [ ] Assign individual owners/reviewers for ready tasks in each layer; confirm the proposed DevOps coordinator and verification record.
- [ ] Configure required checks and review protection on `main`.
- [ ] Extend CI's no-class check to all team-authored Python and add the I/O-boundary check.
- [ ] Verify CI paths and commands against `app/`; preserve lint, offline tests, Docker tests and release automation.
- [ ] Publish configuration/run/test instructions and standards links in README.
- [ ] Review this roadmap with the team and maintain its progress and decisions as tasks merge.

## Outstanding decisions

| Decision | Responsible | Required before |
| --- | --- | --- |
| Instructor topic sign-off and one-paragraph problem statement | Team coordinator to be assigned | G1 completion |
| Correct repository URL in the proposal and Project Initial Details | Team coordinator to be assigned | G5 completion |
| Input, AI, decision and saved-record schemas; error contracts | All layer owners | Cross-layer integration |
| Retained extraction fields and second AI formatting call | Arvin & Guan Feng, Bryan & Xavier | Extraction integration |
| Two-AI-field rule, score use, precedence and exposure outcomes | Bryan & Xavier | Final logic implementation |
| Personal-information/payment categories and supported user actions | Jeremy & Bryan, Bryan & Xavier | Input/logic extension |
| Report status values and transitions | Bryan & Xavier, Jeremy & Bryan | Status-update implementation |
| Timeout/retry policy and live API/model verification | Arvin & Guan Feng | API completion |
| Repeatability and whether viewing/filtering/status updates require API calls | Instructor clarification; team coordinator to be assigned | Dependent record operations |
| Week 7/8 calendar deadlines and final submission evidence | Team coordinator to be assigned | Submission readiness |
| Draft adoption, refactor coordination and proposed DevOps coordinator (Guan Feng) | Team | Week 5 rollout |

## References

- [Input PR #14](https://github.com/lgf2111/phish-report/pull/14) and [extraction branch snapshot](https://github.com/lgf2111/phish-report/tree/613d4fb): unmerged teammate work.
- Team Project Framework - Phase 1: mandatory functions, constraints and deliverables.
- Team Project Specification: collaboration, Docker verification and remaining Week 7/8 checkpoints.
- Project Initial Details: repository access and submission requirements.
- Grading Criteria1: problem clarity, domain integration, procedural logic, function definition, architecture, DevOps and robustness.

The course PDFs are kept locally in `.local/`; these document titles are not links to repository files.

## Submission readiness checklist

Check each item only when its acceptance criteria above pass on the submission version and the evidence is recorded.

- [ ] **G1 — Approved scope:** instructor topic sign-off and one-paragraph problem statement recorded.
- [ ] **G2 — Procedural application:** all four managers and required functions work; procedural, AI-core, validation and I/O constraints verified.
- [ ] **G3 — Automated tests:** offline logic tests, including the two-AI-field rule, pass inside Docker.
- [ ] **G4 — Engineering report:** no more than five pages; data-flow diagram and exception matrix share a page.
- [ ] **G5 — Git repository:** correct URL and access, Project Initial Details submission, descriptive history and reviewed changes verified.
- [ ] **G6 — Docker delivery:** submission version runs with persistent reports and is verified on all six laptops.
- [ ] **G7 — Integrated app:** agreed normal, exposure, uncertain, failure, storage and repeatability cases pass.
- [ ] **G8 — Demonstration:** full pipeline, failures and offline tests rehearsed; every member can explain their contribution.
