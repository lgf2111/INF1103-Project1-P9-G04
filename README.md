# PhishReport

[![CI](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml/badge.svg)](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml)

PhishReport assesses suspicious emails, SMS and chat messages using the Groq API and rule-based scoring. The CLI provides a response priority and recommended actions, and saves assessments locally as JSON. Telegram is the Phase 2 interface: send the bot a suspicious message in a private chat and it replies with the same priority and recommended actions.

**A LOW-priority result does not guarantee that a message is safe.**

## Project layout

| Path | Purpose |
| --- | --- |
| `phishreport/io_manager.py` | Compatibility functions for the I/O manager. |
| `phishreport/io/` | Console adapter, input coordinator, email parsing, folder selection and report presentation. |
| `phishreport/ai_manager.py` | Compatibility functions for AI prompting, requests and validation. |
| `phishreport/ai/` | AI assessment coordinator, prompt builder, completion client and response validator. |
| `phishreport/logic_manager.py` | Apply assessment rules, scoring and routing. |
| `phishreport/logic/` | Assessment rules, scoring, routing, response guidance and report summaries. |
| `phishreport/data_manager.py` | Save, load and query JSON reports. |
| `phishreport/data/` | Report validation and JSON storage. |
| `phishreport/cli/` | Terminal interface: `main.py` composes the four managers through `PhishReportApp`; `web_upload.py` handles browser-based `.eml` uploads. |
| `phishreport/assessment.py` | Shared assessment workflow (AI findings, then business rules) used by the CLI and the bot. |
| `phishreport/bot/` | Telegram interface: launcher, handlers, and chat record and reply formatting. |
| `phishreport/email_html.py` | Convert HTML email content to safe text. |
| `phishreport/local_settings.py` | Manage local preferences. |
| `phishreport/logging_setup.py` | Configure diagnostic logs. |
| `docs/` | Organized guides, teammate handoffs, and project references. |
| `requirements.txt` | Dependencies for Telegram and the offline tests. |
| `tests/core/` | Offline tests for the shared core: AI, logic, data, I/O and the four manager modules. |
| `tests/cli/` | Offline tests for the terminal interface, settings, uploads, the Docker helper and the feature showcase. |
| `tests/bot/` | Offline Telegram handler and launcher checks. |
| `tests/fixtures/` | Public sample emails for testing. |
| `conftest.py` | Shared pytest configuration. |

### Input and output

The CLI uses an `IOManager` instance to collect manual input and coordinate folder
imports and browser uploads. All three paths use the same record builder.
`EmlReader` parses email from disk or uploaded bytes. `EmlFolderPicker` handles
folder selection, and `ReportPresenter` formats assessments and saved reports.
The manager, picker, and presenter use the `Terminal` interface, which tests can
exercise with scripted input and captured output.

### AI assessment

The CLI calls `AIManager.assess(record)` to build a prompt and obtain findings.
The manager uses `GroqClient` by default and accepts an `AIClient` implementation
for offline tests. It parses the completion, validates the findings schema and
checks that extracted details match the original message. Only validated
findings reach the scoring rules.

## Set up

Use **Python 3.14** and [uv](https://docs.astral.sh/uv/) to match the CI and
Docker environment. Install uv once using its
[official instructions](https://docs.astral.sh/uv/getting-started/installation/),
then run commands from the repository root. No project virtual environment
needs to be created or activated.

If you already have a `.env` file, add the settings you need to it. Otherwise,
copy the example file.

**Windows PowerShell**

```powershell
Copy-Item .env.example .env
```

**macOS or Linux**

```bash
cp .env.example .env
```

Add your Groq API key to `.env`:

```text
GROQ_API_KEY=your_key_here
```

Get an API key from the [Groq console](https://console.groq.com). A key is required for live assessments but **not** for offline tests. Do not commit `.env` or enter real passwords or one-time codes as sample data.

## Run and test

Start the application:

```bash
uv run --python 3.14 --no-project --with-requirements requirements.txt python -m phishreport.cli
```

You can manually check a suspicious message, import or upload an `.eml` email, view saved reports, and summarize them. New assessments require a valid response from the Groq API.

### Report summary

**Problem:** Saved reports are only a numbered list, so it is hard to see how many
messages were high priority, which channel they came from, or whether people who
reported clicking a link are a growing share.

**How to use it:** Choose **5. Summarize saved reports** in the CLI menu. Optionally
filter by priority (high, medium, low) and channel (email, sms, chat), or press Enter
to include everything. The summary shows counts by priority and channel, the average,
highest and lowest rule-based score, and how many reports include a clicked link, a
downloaded file or a submitted password or code.

**Classes:**

| Class | Role |
| --- | --- |
| `ReportFilter` | Immutable criteria (priority, channel, minimum score) with a `matches(record)` predicate. Unknown values raise `ValueError`. |
| `StoredReport` | Read-only view that hides the current (`result`) and older (top-level score) record layouts. |
| `SummaryMetric` (abstract) | Contract for one summary block. Subclasses: `PriorityBreakdown`, `ChannelBreakdown`, `ScoreStatistics`, `ReportedExposure`. |
| `ReportSummarizer` | Runs each metric over the records and builds a `ReportSummary`. A new statistic is a new `SummaryMetric` subclass, with no change to the summarizer. |
| `LogicManager` | `build_filter()` and `summarize()` expose the feature to the application. |
| `DataManager` | The existing `query()` returns only the records that match the filter. |
| `IOManager` / `ReportPresenter` | `collect_summary_filter()` asks for the criteria and `display_summary()` prints the result. |
| `PhishReportApp` | `summarize_reports()` connects the four managers. |

**Tests:** `tests/core/test_summary.py` covers filter matching and validation, both
stored layouts, each metric (including unclassifiable values), a custom metric
subclass, an empty history, an unreadable history file, the filter prompts, the printed
summary and the menu flow. No AI service is needed.

### Telegram bot

The bot opens **PhishReport** on `/start` and shows one **Check connection**
button. The button acknowledges the tap and checks whether the existing
DataManager can read local history. Missing or empty history passes. If the
read fails, the bot asks the user to retry.

**Assessing a message:** send any text message to the bot in a private chat. The
bot builds a chat record, runs the shared `AssessmentService` (AI findings, then the
rule-based score) and replies with the priority, score, reasons and recommended
actions. It saves each assessment to the same `reports.json` the CLI uses, so
**View saved reports** and **Summarize saved reports** in the CLI include them.
A chat message carries no attachment or interaction details, so nothing is recorded as
clicked, downloaded or submitted; the score reflects the AI findings only. AI calls
run on a worker thread so the bot stays responsive, and saves take turns.

Every assessment calls the Groq API with your key. Leaving `TELEGRAM_ALLOWED_CHAT_ID`
blank lets any private chat that finds the bot use that quota, so set the chat ID if
the bot is public.

#### Configure and run the bot

Create a bot with [BotFather](https://t.me/BotFather). By default the bot
answers any private chat and ignores groups and channels. To restrict it to one
chat, open that private chat with the bot's username, send `/start`, and use the
[Telegram Bot API](https://core.telegram.org/bots/api#getupdates) to get
`message.chat.id` from that update. Confirm `message.chat.type` is `private`.

Add these settings to the repo root's `.env` file. Git ignores `.env`. If you
previously used `.env.telegram`, move the Telegram settings into `.env`.

```dotenv
TELEGRAM_BOT_TOKEN=<token from BotFather>
# Optional: leave blank to accept any private chat, or set a positive chat ID
# to restrict the bot to that chat.
TELEGRAM_ALLOWED_CHAT_ID=<optional positive private chat ID>
```

Start Docker and run this from Bash or Git Bash:

```bash
bash run.sh telegram
```

The helper builds the `telegram` target if needed and mounts
`.phishreport-data/` at `/data`, where the bot reads and writes `reports.json`.
It needs `GROQ_API_KEY` in `.env` to assess messages.
It uses outbound polling with one running instance per token.

For a first run with empty history, the direct commands also work in PowerShell:

```text
docker build --target telegram -t phishreport-telegram .
docker run --rm --env-file .env phishreport-telegram
```

To check an existing `.phishreport-data/` directory with the direct command,
add `--mount "type=bind,source=${PWD}/.phishreport-data,target=/data,readonly"`
before the image name. Rebuild the image after changing the code.

Outside Docker, set both Telegram settings in the current shell environment
and launch from the repository root:

```bash
uv run --python 3.14 --no-project --with-requirements requirements.txt python -m phishreport.bot
```

The local launcher reads `reports.json` from the working directory. Set
`PHISHREPORT_REPORTS_PATH` to select a different file.

#### Verify the live connection

1. In the configured private chat, send `/start` and look for the welcome
   with one **Check connection** button.
2. Tap the button. Telegram should clear the tap indicator and the bot should
   reply **Connection check passed.** Missing or empty history should pass.
3. If a second Telegram account is available, send `/start` from its private
   chat with the same bot and confirm it receives no menu.

#### Add the next handler

Add an async method to `TelegramIOManager` in `phishreport/bot/handlers.py`.
Use the same private-chat check before accessing app data. Register the method
in `phishreport/bot/main.py` and test it with fake updates in `tests/bot/`.
Report browsing and summaries still run through the CLI.

### Offline tests

Run the automated tests:

```bash
uv run --python 3.14 --no-project --with-requirements requirements.txt pytest
```

Run a specific test suite or the feature showcase:

```bash
uv run --python 3.14 --no-project --with-requirements requirements.txt pytest tests/core/test_logic_manager.py -q
uv run --python 3.14 --no-project --with-requirements requirements.txt pytest tests/core/test_io_core.py -q
uv run --python 3.14 --no-project --with-requirements requirements.txt pytest tests/cli -q
uv run --python 3.14 --no-project --with-requirements requirements.txt pytest -m demo -v
```

The application suite uses fake completion clients and mocked Groq HTTP calls
to check prompt handling, retries, response validation and CLI behavior.
The Telegram tests use fake updates and temporary data. Neither suite needs
credentials once dependencies are installed.

### Assessment policy

The first matching rule determines the score and priority. Every new assessment requires valid AI findings.

| Condition | Score | Priority |
| --- | --- | --- |
| Reported password/OTP disclosure | 90 | HIGH |
| AI suspicious and reported click/download | 80 | HIGH |
| AI suspicious and AI credential request | 60 | MEDIUM |
| AI suspicious | 45 | MEDIUM |
| AI credential request | 40 | MEDIUM |
| Reported click/download | 35 | MEDIUM |
| AI insufficient context | 20 | LOW |
| Otherwise | 10 | LOW |

**HIGH** begins at 70; **MEDIUM** begins at 35. Scores represent response priority, not the probability that a message is malicious.

### Import an email

PhishReport supports three ways to submit a message:

1. **Manual input:** Enter an email, SMS or chat message directly.
2. **Folder import:** Select an exported `.eml` email from a local folder.
3. **Browser upload:** Upload one `.eml` email through the local browser page at `http://localhost:8000` when the uploader is running.

Both `.eml` methods use the same email parser. The application reads supported text/HTML email content but **does not analyse attachments or embedded images**. Non-`.eml` browser uploads are rejected. Each imported file is limited to **2 MiB**. Users are asked separately whether they clicked links, downloaded files or disclosed credentials.

## Run Docker with persistent reports

Install and start Docker Desktop (or Docker Engine on Linux). For CLI analysis,
copy `.env.example` to `.env` and add your Groq API key. On Windows, use
PowerShell to prepare the settings file, then open Git Bash in the repository
(Git for Windows) or use WSL:

```powershell
Copy-Item .env.example .env
notepad .env
```

On macOS/Linux, prepare it with:

```bash
cp .env.example .env
# Edit .env and set GROQ_API_KEY.
```

Then run commands from the repository root in Bash on macOS/Linux or Git
Bash/WSL on Windows:

```bash
bash run.sh build
bash run.sh test
bash run.sh run
```

`run.sh` builds the image automatically when needed, so `bash run.sh run` is
also enough for a first launch after configuring `.env`. Docker keeps reports,
settings and logs in the host project's `.phishreport-data/` directory so they
remain available between runs. The runner mounts the project's `emails/`
directory for local `.eml` imports and makes the browser uploader available at
`http://localhost:8000`.

To build the Telegram target and run the full suite inside it without
credentials or external network access:

```bash
docker build --target telegram -t phishreport-telegram .
docker run --rm --network none phishreport-telegram python -m pytest
```

## Team contributions

The following contributions are based on the project's recorded commits and merged pull requests. Links are provided for attribution and review.

| Team member | Recorded contributions | Evidence |
| --- | --- | --- |
| Lee Guan Feng | Application scaffolding, Groq transport, initial offline tests, Docker helper, CI/Ruff/class guard and release automation; later folder preferences/pagination, browser uploader, diagnostic logging and configurable retries. | [Foundation](https://github.com/lgf2111/INF1103-Project1-P9-G04/commit/fa11bf3), [offline tests](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/7), [release workflow](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/11), [folder picker](https://github.com/lgf2111/INF1103-Project1-P9-G04/commit/f91c0b5), [uploader](https://github.com/lgf2111/INF1103-Project1-P9-G04/commit/e9239a7), [logging](https://github.com/lgf2111/INF1103-Project1-P9-G04/commit/210a6cd). |
| Jeremy Goh | Validated manual input, exposure questions and reusable choice validation; EML import, MIME/decoding limits, EML-only upload restrictions and associated regressions; co-authored the common real-email parser integration. | [Input](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/19), [choice validation](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/23), [EML import](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/39), [upload hardening](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/68), [co-authored parser](https://github.com/lgf2111/INF1103-Project1-P9-G04/commit/18409ab). |
| Bryan Lee | Result, detailed-record and saved-summary displays, including the related display regressions. | [Display implementation](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/22). |
| Bryan Ow | Initial record validation/evaluation and score/priority persistence; null/flat saved-result displays; later credential-only, interaction-only and uncertainty scoring refinements, logic tests and Docker persistence work. | [Initial evaluation](https://github.com/lgf2111/INF1103-Project1-P9-G04/commit/a442dc4), [saved displays](https://github.com/lgf2111/INF1103-Project1-P9-G04/commit/d5a4f9a), [policy and Docker](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/64), [co-authored persistence fix](https://github.com/lgf2111/INF1103-Project1-P9-G04/commit/2f6c56a). |
| Xavier Heng | Extraction prompts/validation and contact-format boundaries, early AI-to-logic integration, public route interface and logic tests; migrated storage to the current version-2 JSON contract and adapted its tests. Earlier database work remains in Git history and is superseded in the submitted application. | [Extraction validation](https://github.com/lgf2111/INF1103-Project1-P9-G04/commit/f794b76), [contact boundaries](https://github.com/lgf2111/INF1103-Project1-P9-G04/commit/613d4fb), [route interface](https://github.com/lgf2111/INF1103-Project1-P9-G04/commit/abe2828), [JSON migration](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/69). |
| Arvin Lum | Strict API/envelope/schema/source validation, combined single-call assessment and first-match policy integration; real-email/browser reliability, atomic history recovery and Docker fixes; physical manager files, procedural helpers, submission audit, regression consolidation/showcase and document reconciliation. These changes retain the original layer contributions above. | [AI integration](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/25), [real-email integration](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/59), [Docker fix, co-authored with Lee Guan Feng and Bryan Ow](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/67), [history recovery](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/72), [manager files](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/73), [final audit](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/79), [test simplification](https://github.com/lgf2111/INF1103-Project1-P9-G04/pull/81). |
