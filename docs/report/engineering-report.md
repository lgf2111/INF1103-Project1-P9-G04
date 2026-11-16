# PhishReport — Engineering Report (draft)

**Team:** LAB-P9-G4 · **Module:** INF1103 Programming Fundamentals with DevOps · **Phase 2**

This draft holds the evidence-backed sections. Diagrams are generated, not drawn:
`python scripts/report_assets.py` writes `class-diagram.mmd`, `data-flow.mmd` and
`oop-evidence.md` from the source tree, so the report cannot drift from the code.

## 1. What the system does

PhishReport assesses a suspicious email, SMS or chat message. Every record passes
through the AI Manager, which returns validated findings; the Logic Manager turns those
findings and the user's reported exposure into a 0-100 response-priority score, a
priority band and recommended actions. Reports are stored locally as JSON or SQLite and
can be filtered and summarised. The same core runs behind a CLI and a Telegram bot.

## 2. Architecture

The four Phase 1 responsibilities remain identifiable, now as objects:

| Manager | Responsibility | Package |
| --- | --- | --- |
| IOManager | Collect and validate input; render results | `phishreport/io/` |
| AIManager | Build the prompt, call the provider, validate the reply | `phishreport/ai/` |
| LogicManager | Apply domain rules, score, route, explain | `phishreport/logic/` |
| DataManager | Persist, load, query and replace reports | `phishreport/data/` |

Between them sits `AssessmentService` (`phishreport/assessment.py`), the single
definition of an assessment used by both interfaces. It holds the AI and Logic managers
it is given (association) and never bypasses the AI: the outcome is built only from
validated findings.

### Class diagram

Render `docs/report/class-diagram.mmd` with any Mermaid renderer. It shows the manager
classes, the `ReportStorage` hierarchy, the `PriorityRule` hierarchy, the renderer
contract and the command objects.

### Data flow

Render `docs/report/data-flow.mmd`. A record moves IOManager → AIManager → LogicManager
→ back to the interface, with DataManager writing the report. The AI step is mandatory:
a failure there aborts the assessment rather than producing a verdict.

## 3. Mandatory OOP concepts

The generated table in `docs/report/oop-evidence.md` cites a real file and line for each
concept. Summary:

- **Classes and objects** — the managers, storages, rules, renderers and commands are
  instantiated by the running application; no module-level procedural pipeline remains.
- **Encapsulation** — manager state is private (`_storage`, `_validator`, `_rules`) and
  reached only through methods.
- **Abstract class** — `PriorityRule` (`phishreport/logic/rules/base.py`) declares
  `matches` and `score` as abstract operations over an ordered rule set.
- **Inheritance** — `JsonReportStorage` and `SqliteReportStorage` both specialise
  `ReportStorage`; eight rule classes specialise `PriorityRule`.
- **Interface / contract** — `ReportStorage` is an ABC with two production
  implementations; `Terminal` and `AIClient` are Protocols used for test doubles.
- **Association** — `AssessmentService` refers to the AI and Logic managers it receives.
- **Aggregation** — `PriorityRuleEngine` accepts a caller-owned rule set that outlives it.
- **Composition** — with no rule set supplied, the engine creates and owns its default
  rules; they are destroyed with it.
- **Polymorphism** — `PriorityRuleEngine.score` iterates rules and calls the shared
  contract; there is no `isinstance` branch and no rule-specific code in the engine.

## 4. SOLID justification

**Single Responsibility.** Each collaborator owns one reason to change.
`ReportValidator` validates schemas; `JsonReportStorage` reads and writes JSON;
`ReportPresenter` formats; `AssessmentService` sequences AI then logic. A change to the
storage format touches the storage class and its tests, not the managers.

**Open/Closed.** Two seams are open for extension without modifying callers. A new
scoring rule is a new subclass of `PriorityRule` registered in the engine's default set;
a new storage backend is a new `ReportStorage` implementation selected by the storage
factory. Neither requires editing the manager that uses it.

**Liskov Substitution.** `ReportStorage`'s contract is written in the base class
("reads return fresh, independently mutable data, or [] for absent storage; malformed
contents raise ValueError; I/O errors raise OSError"). The same test suite runs against
`JsonReportStorage` and `SqliteReportStorage` (`tests/core/test_sqlite_storage.py`,
`tests/core/test_storage_factory.py`), which is the evidence that the substitution
holds rather than an assertion that it does.

**Interface Segregation.** Renderers receive an `AssessmentDocument` and return text or
HTML; they do not know about managers, storage or Telegram.

**Dependency Inversion.** Managers depend on contracts (`ReportStorage`,
`PriorityRule`, `AIClient`, `Terminal`), not on concrete classes; production wiring
happens at the edges (CLI and bot entry points).

## 5. New feature

**Filterable report summary with correction feedback.** The summary answers questions
the raw history could not: how many reports fell into each priority, which channel they
came from, the score range, and how many involved a clicked link, a download or a
disclosed password. It is accessed through the CLI menu and summarised per filter.

The feedback workflow records whether an assessment was right, wrong or partly wrong,
keyed to the assessment id. It is an annotation, never a new assessment, so the
AI-centred pipeline is preserved. Classes: `ReportSummarizer`, `SummaryMetric` and its
subclasses, `ReportFilter`, `FeedbackService`, `FeedbackStore`, plus the CLI and bot
handlers that call them.

Tests: `tests/core/test_summary.py`, `tests/core/test_feedback.py`,
`tests/cli/test_assessment_errors.py`, `tests/bot/test_handlers.py`.

## 6. Advanced feature — Telegram as GUI

The Telegram bot is the graphical interface: inline keyboards, rendered result cards,
multi-select exposure questions and status commands, running against the same managers
as the CLI. Screens are built from `AssessmentDocument` by `AssessmentRenderer` and the
`DocumentRenderer` implementations (`PlainTextRenderer`, `HTMLAlertRenderer`);
transport-specific escaping and length limits stay in the adapter.

The flow that makes the GUI more than a text pipe: after an assessment the bot asks
whether the user clicked, downloaded, entered a password or entered a one-time code.
Answers re-score the same assessment using the findings already obtained (no second AI
call), which is what lets a chat assessment reach the HIGH band. Sessions are keyed by
chat, user and message, expire after thirty minutes, and save once when the user
finishes or skips.

Evidence: `phishreport/bot/exposure.py`, `phishreport/bot/handlers.py`,
`phishreport/io/html_alert_renderer.py`, `tests/bot/test_exposure.py`,
`tests/bot/test_dispatch.py`.

## 7. Exception handling

`docs/exception-matrix.md` lists every failure with its typed error, the exact user
message, the fallback behaviour and the test that proves it. The rule: a failure never
becomes a LOW verdict and never invents data. Programmer errors propagate so a defect
fails loudly instead of hiding behind a friendly sentence.

## 8. Testing and DevOps

- Offline suite: 3102 tests, no live API; provider calls use stubs and fixtures.
- CI (`.github/workflows/ci.yml`): ruff, the offline suite, and a Docker job that runs
  the same suite inside the Telegram image. A release workflow publishes on `v*` tags.
- Docker: one root `Dockerfile` with `cli` and `telegram` targets; `run.sh` wraps build,
  run and test commands.

## 9. Contributions

See the contribution table in the root `README.md` and the TeamAId task export for the
per-member record.

## 10. Known limits

- A LOW priority result does not guarantee a message is safe; the score ranks response
  urgency, not the probability that the message is malicious.
- Chat assessments without exposure answers rely on AI findings alone, which caps them
  at MEDIUM by design.
- The Gmail monitor stores an app password on disk (mode 0600) because polling needs it;
  unlinking deletes it.
