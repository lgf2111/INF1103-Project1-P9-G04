# PhishReport

[![CI](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml/badge.svg)](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml)

PhishReport assesses suspicious emails, SMS and chat messages using the Groq API and rule-based scoring. The CLI provides a response priority and recommended actions, and saves assessments locally using JSON or SQLite. Telegram is the Phase 2 interface: send the bot a suspicious message in a private chat and it replies with the same priority and recommended actions. It can also watch a linked Gmail inbox and message you when a new email looks like phishing.

**A LOW-priority result does not guarantee that a message is safe.**

## Project layout

| Path | Purpose |
| --- | --- |
| `phishreport/io_manager.py` | Compatibility functions for the I/O manager. |
| `phishreport/io/` | Console adapter, input coordinator, email parsing, folder selection and assessment document renderers. |
| `phishreport/ai_manager.py` | Compatibility functions for AI prompting, requests and validation. |
| `phishreport/ai/` | AI assessment coordinator, prompt builder, completion client and response validator. |
| `phishreport/logic_manager.py` | Apply assessment rules, scoring and routing. |
| `phishreport/logic/` | Assessment rules, scoring, routing, response guidance and report summaries. |
| `phishreport/data_manager.py` | Public DataManager interface for saving, loading and querying reports. |
| `phishreport/data/` | Report validation, JSON/SQLite storage, environment selection and explicit migration. |
| `phishreport/cli/` | Terminal interface: `main.py` composes the four managers through `PhishReportApp`; `web_upload.py` handles browser-based `.eml` uploads. |
| `phishreport/assessment.py` | Shared assessment workflow (AI findings, then business rules) used by the CLI and the bot. |
| `phishreport/bot/` | Telegram interface: launcher, handlers, chat record and reply formatting, and the Gmail link and background email monitor (`gmail.py`, `gmail_handlers.py`, `monitor.py`). |
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
folder selection. `AssessmentRenderer` builds ordered, neutral assessment
sections, and `PlainTextRenderer` formats them for the CLI and Telegram result
replies. `HTMLAlertRenderer` renders the shared assessment fields in Gmail alert
markup. `ReportPresenter` writes console results and continues to format saved
reports. Telegram adapters keep HTML escaping, alert clipping, exposure notices
and reply-length limits at the transport boundary.

### AI assessment

The CLI calls `AIManager.assess(record)` to build a prompt and obtain findings.
The manager uses `GroqClient` by default and accepts an `AIClient` implementation
for offline tests. It parses the completion, validates the findings schema and
checks that extracted details match the original message. Only validated
findings reach the scoring rules.

### Report storage and migration

Both launchers use `create_report_storage()` to select a `ReportStorage`
implementation. `DataManager` keeps the same save, load and query behavior.
SQLite uses Python's standard-library `sqlite3` module.

| Process environment | Behavior |
| --- | --- |
| `PHISHREPORT_STORAGE` unset or `json` | JSON storage; the default is `reports.json`. |
| `PHISHREPORT_STORAGE=sqlite` | SQLite storage; the default is `reports.sqlite3`. |
| `PHISHREPORT_REPORTS_PATH` | JSON path; SQLite replaces its final suffix with `.sqlite3`. For example, `archive/history.json` selects `archive/history.sqlite3`. Parent directories must already exist. |

Unsupported selectors raise `ValueError`. Storage selection happens before the
CLI loads `.env`, so set these variables in the shell for local launches.
Docker's `--env-file .env` supplies them before startup. In the Telegram image,
leave `PHISHREPORT_REPORTS_PATH` unset to retain `/data/reports.json`; selecting
SQLite then uses `/data/reports.sqlite3`. The `run.sh` CLI workflow runs from
`/data`, so its default relative paths also use the mounted data directory.

For a local SQLite CLI session, run from the repository root:

```powershell
$env:PHISHREPORT_STORAGE = "sqlite"
uv run --python 3.14 --no-project --with-requirements requirements.txt python -m phishreport.cli
```

In Bash:

```bash
PHISHREPORT_STORAGE=sqlite uv run --python 3.14 --no-project --with-requirements requirements.txt python -m phishreport.cli
```

The same selector applies to `python -m phishreport.bot`; its Telegram and Groq
credentials must also be present in the process environment.

Switching backends does not import existing history automatically. Stop the CLI,
bot and other writers, then migrate an existing JSON file explicitly:

```text
uv run --python 3.14 --no-project --with-requirements requirements.txt python -c "from phishreport.data.migration import migrate_json_to_sqlite; print(migrate_json_to_sqlite('reports.json', 'reports.sqlite3'))"
```

The printed number is the number of imported records. An identical rerun prints
`0`. The helper preserves source bytes, record order, historical fields and
legitimate duplicate records. It refuses a different nonempty destination or
source/destination aliases. Missing or malformed source files fail before target
initialization. Keep the source JSON as a backup.

For an existing `.phishreport-data/reports.json`, use the built Telegram image
with the entire data directory mounted writable. This command works in
PowerShell and Bash from the repository root:

```text
docker run --rm --network none --mount "type=bind,source=${PWD}/.phishreport-data,target=/data" phishreport-telegram python -c "from phishreport.data.migration import migrate_json_to_sqlite; print(migrate_json_to_sqlite('/data/reports.json', '/data/reports.sqlite3'))"
```

After migration, set `PHISHREPORT_STORAGE=sqlite` in the `.env` passed to Docker
and restart the bot. SQLite needs a writable directory for the database and its
`-wal` and `-shm` sidecars. Relative local paths follow the working directory when
an operation runs. Use one application writer per history file: transactions
protect a replacement, while `DataManager.save()` still performs separate read
and write operations. The bot serializes its own writers with its save lock.

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

**Tests:** `tests/core/test_summary.py` covers filter matching and validation,
current and historical layouts, each metric (including unclassifiable values),
a custom metric subclass, an empty history, an unreadable history file, the filter prompts, the printed
summary and the menu flow. No AI service is needed.

### Shared conversation commands

Enter these commands at the CLI menu or in the bot's private chat. CLI choices
**1–6** remain unchanged.

| Command | CLI | Telegram |
| --- | --- | --- |
| `/check <text>` | Assess pasted chat text using the existing link, file and exposure prompts; save and display the result. | Assess the text once, then answer the existing exposure questions before finishing or skipping to save. Answers reuse the original AI findings. |
| `/help` | List the shared commands. | List the shared commands; the Gmail commands below remain available. |
| `/status` | Show that the CLI conversation is active and count saved reports. | Count the requesting user's active exposure sessions awaiting answers and count saved reports. |

Status counts reports from the configured history backend using strict loading;
a read failure shows an error rather than a zero count. It does not request AI
findings or save a report. Telegram's active-session count excludes other users
and chats, expired sessions, and completed or saved assessments. It does not
remove cached sessions or completed reports awaiting a save retry.

Command names are exact and case-sensitive. `/check` without text shows usage.
Bot-addressed forms such as `/check@botname` are not recognized by the shared
router and follow Telegram's default content path.
The router accepts leading whitespace and preserves the argument's internal and
trailing whitespace. Ordinary pasted Telegram text still takes the default
assessment path. Unknown slash input also takes that path in Telegram; the CLI
instead shows its invalid-choice message. While Telegram is collecting a feedback
comment, text reaching this handler, including `/check`, `/help` and `/status`,
is treated as that comment. The existing Start and Gmail handlers retain priority.

`phishreport/io/commands.py` defines the `Command` ABC, request/reply models and
router. Check, Help and Status implement that contract in separate files and use
injected services; the I/O package imports neither Telegram nor the bot package.
Both transports execute the same command implementations, while input collection,
presentation, exposure follow-up and persistence remain adapter responsibilities.

### Telegram bot

The bot opens **PhishReport** on `/start` and shows one **Check connection**
button. The button acknowledges the tap and checks whether the existing
DataManager can read local history. Missing or empty history passes. If the
read fails, the bot asks the user to retry.

**Assessing a message:** paste text in a private chat. The bot calls the shared
`AssessmentService` once for validated AI findings and shows a **Provisional
assessment** with priority, score, reasons and recommended actions. It extracts
the first supported URL and filename clue (or an attachment mention) from the
text; these are not verified attachments or evidence of any interaction.

Two questions share one keyboard:

- Interaction: **Clicked link**, **Downloaded file**, **Both**, **Neither**.
- Disclosure: **Password**, **One-time code**, **Neither password nor code**.

Selections update the score using retained findings, without another AI call.
Choose **Finish and save** or **Skip unanswered** to save the completed report.
Both retain partial answers; unanswered fields remain **Unconfirmed**, and the
reply says **Exposure unconfirmed** whenever any question is unanswered. Neither
the initial reply nor answer selection saves history. Unfinished sessions expire
after 30 minutes or bot restart without being saved. A completed report whose
write fails stays available for **Retry saving** while the process remains alive,
even past the pending timeout. **Report saved locally** appears only after a
successful write.

AI and storage work run on worker threads, and message/callback handlers do not
wait for future answers. Another message or command can be handled while questions
are pending or a callback save is in progress. Repeated finalization uses one
cached report and avoids another save within the retained session; this is
in-process protection, not durable distributed exactly-once delivery.

Completed Telegram text reports use schema v3 with extracted metadata and nullable
exposure answers. Configure the CLI with the same backend and path to see them in
**View saved reports** and **Summarize saved reports**, including saved links and
Unconfirmed answers. Unknowns do not count as confirmed exposure. Existing
CLI assessments and Gmail monitoring continue to save v2 reports; supported older
history remains readable. See [backend contracts](docs/handoffs/BACKEND_HANDOFF.md).

Each new assessment requests AI findings using your Groq key; provider retries or
fallback may make multiple HTTP attempts. Answers, rescoring and completed-save
retries request no fresh findings. Leaving `TELEGRAM_ALLOWED_CHAT_ID`
blank lets any private chat that finds the bot use that quota, so set the chat ID if
the bot is public.

#### Gmail phishing monitor

Link a Gmail account from the bot's private chat and PhishReport checks new mail in the
background and messages you when an email looks like phishing.

| Command | What it does |
| --- | --- |
| `/linkgmail you@gmail.com <app password>` | Checks the login, deletes your message so the password is not left in the chat, and starts watching the inbox. Send it with no arguments for the setup steps. |
| `/checkmail` | Checks your newest 20 unread emails right now and replies with a summary. |
| `/unlinkgmail` | Stops watching and deletes the saved app password. |

**How it works**

- Gmail is read over IMAP in read-only mode, so reading never marks mail as read.
- Every 60 seconds the monitor fetches mail that arrived after linking, runs each email
  through the shared `AssessmentService` and saves it to the selected report history. Read
  state is ignored; the newest message number it has handled is stored, so no email is
  checked twice by the background check. `/checkmail` is the way to re-check an email.
- An email scored **MEDIUM** or **HIGH** triggers a Telegram message with the sender,
  subject, score, why it was flagged, what to do, and a link that opens the email in Gmail
  (the link needs you to be signed in to that Gmail account).
- A temporary AI failure keeps the email for the next cycle. A rejected login unlinks the
  account and tells you. One email that fails unexpectedly is skipped, not retried forever.
- The terminal running the bot prints `[email] ...` progress lines (counts, priorities and
  failure types only, never email text or the password).
- The AI sees the email text only. Links and attachments are not extracted, so there is no
  rule-based boost for them.

**Get an app password.** Gmail needs a Google app password, not your normal password:

1. Turn on 2-Step Verification, with a phone prompt or authenticator app. A security key
   or passkey alone is not enough.
2. Create an app password at <https://myaccount.google.com/apppasswords>.
3. Send `/linkgmail you@gmail.com abcd efgh ijkl mnop` to the bot.

If Google says "The setting you are looking for is not available for your account", check
that 2-Step Verification is on, Advanced Protection is off, and the account is not a school
or work account whose admin blocks app passwords (use a personal Gmail instead).

**Security.** The app password must be stored to keep polling. It is saved in
`.phishreport-data/gmail_accounts.json` (set `PHISHREPORT_GMAIL_PATH` to move it) with
owner-only permissions, is never logged, and is excluded from Git. Telegram may keep your
`/linkgmail` message on its servers even after the bot deletes it, so revoke the app
password when you are done testing. Each chat links its own account; set
`TELEGRAM_ALLOWED_CHAT_ID` if the bot is public.

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
`.phishreport-data/` at `/data`, where the bot reads and writes `reports.json`
or, with `PHISHREPORT_STORAGE=sqlite`, `reports.sqlite3`.
It needs `GROQ_API_KEY` in `.env` to assess messages.
It uses outbound polling with one running instance per token. When the bot is ready, the
terminal prints your bot's username and the next steps (`/start`, `/linkgmail`,
`/checkmail`). Press Ctrl+C to stop it.

For a first run with empty history, the direct commands also work in PowerShell:

```text
docker build --target telegram -t phishreport-telegram .
docker run --rm --env-file .env phishreport-telegram
```

To persist history with the direct command, create `.phishreport-data/` first
and add `--mount "type=bind,source=${PWD}/.phishreport-data,target=/data"`
before the image name. Keep the mount writable for reports, Gmail settings and
SQLite sidecars. Rebuild the image after changing the code.

Outside Docker, set both Telegram settings in the current shell environment
and launch from the repository root:

```bash
uv run --python 3.14 --no-project --with-requirements requirements.txt python -m phishreport.bot
```

The local launcher defaults to JSON in `reports.json`. Set
`PHISHREPORT_REPORTS_PATH` to choose the history path and `PHISHREPORT_STORAGE`
to select JSON or its SQLite sibling, as described under
[report storage and migration](#report-storage-and-migration).

#### Verify the live connection

1. In the configured private chat, send `/start` and look for the welcome
   with one **Check connection** button.
2. Tap the button. Telegram should clear the tap indicator and the bot should
   reply **Connection check passed.** Missing or empty history should pass.
3. If a second Telegram account is available, send `/start` from its private
   chat with the same bot and confirm it receives no menu.

#### Check the exposure flow with an isolated history

Use an activated Python 3.12 environment with dependencies installed, from the
repository root. In PowerShell, choose a fresh demo path and one backend before
starting the bot (Telegram settings and `GROQ_API_KEY` must already be in the shell):

```powershell
New-Item -ItemType Directory -Force .local/telegram-demo | Out-Null
$env:PHISHREPORT_REPORTS_PATH = "$PWD/.local/telegram-demo/reports.json"
$env:PHISHREPORT_STORAGE = "json"
python -m phishreport.bot
```

Repeat the checklist with `PHISHREPORT_STORAGE = "sqlite"`; it uses the sibling
`reports.sqlite3`. Keep that same selector and path when starting the CLI with
`python -m phishreport.cli`. This demo history is separate from normal reports.
Selections in this checklist simulate exposure only: do not visit the SMS link
or enter/send any real password or one-time code.

1. Paste your real suspicious SMS. Check the initial provisional reply and
   questions; history must not yet gain a report. The pasted SMS is a chat input.
2. Select **Clicked link**, then **Finish and save**. Expect **80 / HIGH** if
   the AI findings are suspicious. With a new submission, select **Password**
   or **One-time code** and finish: expect **90 / HIGH** after valid AI findings.
3. On a new submission, choose **Skip unanswered** without answers. A suspicious
   AI baseline stays **MEDIUM** (60 if it also requests credentials, otherwise
   45). Check **Unconfirmed**. On another, select **Clicked link**, then skip;
   the click stays Yes and disclosure stays Unconfirmed.
4. Leave questions pending, send a second message and `/start`, and check both
   receive replies. Repeat a Finish/Skip callback if available and confirm the
   completed report appears only once in history.
5. Stop and restart the bot: unfinished questions are unavailable and unsaved.
   Stop it again, start the CLI with the same backend/path, and inspect saved
   links and answers in history and summaries. Repeat for both backends.

A live SMS demo, mounted container restart, and remote CI each require their own
observed evidence; offline tests alone do not establish those results.

#### Extend commands or add a transport-specific handler

For a shared operation using the existing capabilities and execution policies,
add one public `.py` file directly under `phishreport/io/command_plugins/`.
`command_catalog.py` discovers immediate modules in that fixed internal package
in filename order; private modules and subpackages are excluded. Each module
exports `create_command(capabilities) -> Command`. Both adapters discover the
same commands, Help reads their live catalog, and Telegram builds command-menu
metadata automatically at startup. Restart the bot to refresh its menu.

For example, save this as `phishreport/io/command_plugins/ping.py`:

```python
from phishreport.io.command_catalog import CommandCapabilities
from phishreport.io.commands import Command, CommandReply, CommandRequest


class PingCommand(Command):
    name = "ping"
    help_text = "Check that the conversation is responding"

    def execute(self, request: CommandRequest) -> CommandReply:
        return CommandReply("Pong", "text")


def create_command(capabilities: CommandCapabilities) -> Command:
    return PingCommand()
```

Factories receive frozen `CommandCapabilities` with record preparation,
assessment, session status, report count and the live command catalog. Construct
the command without calling these services, performing I/O or mutating the
catalog during discovery. These are trusted internal modules, not arbitrary
external plugins; import, factory and registration failures are not silently
ignored.

The default `CommandPolicy` uses ordinary reply execution and a generic command
failure message. Commands may select the existing assessment or history failure
policies. Assessment execution must publish a `CheckOutcome` and an assessment
reply; Telegram also requires retained AI findings for exposure rescoring. An
ordinary reply's `kind` alone cannot request persistence. New capabilities or
transport-specific interaction flows still require adapter integration.

Use unique lowercase command names and reserve `start`, `linkgmail`, `checkmail`
and `unlinkgmail` for the native Telegram handlers. Telegram startup validates
names of at most 32 characters, descriptions of 1–256 characters, and a maximum
of 100 menu entries including the native commands, following its
[command metadata](https://core.telegram.org/bots/api#botcommand) and
[menu limits](https://core.telegram.org/bots/api#setmycommands).

For Telegram-only interactions, add an async method to `TelegramIOManager` in
`phishreport/bot/handlers.py`, keep the private-chat check, and register its handler
in `phishreport/bot/main.py`. Test shared commands with fake services and verify
adapter dispatch with offline updates. Report browsing and summaries remain in
the CLI.

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

For the shared-command contract, import-direction and transport checks in an
activated Python 3.12 environment, run:

```text
python -m pytest tests/core/test_commands.py tests/core/test_command_policy.py tests/core/test_command_catalog.py tests/core/test_check_command.py tests/core/test_help_command.py tests/core/test_status_command.py tests/core/test_check_command_factory.py tests/core/test_help_command_factory.py tests/core/test_status_command_factory.py -q
python -m pytest tests/cli/test_cli_check_command.py tests/cli/test_cli_menu_commands.py tests/cli/test_cli_status_command.py tests/cli/test_cli_discovered_commands.py -q
python -m pytest tests/bot/test_bot_shared_commands.py tests/bot/test_bot_status_command.py tests/bot/test_bot_discovered_commands.py tests/bot/test_bot_command_menu.py tests/bot/test_dispatch.py -q
```

The dispatch suite includes combined discovery checks with a new one-file
command, both transports, Help, Telegram menu metadata and JSON/SQLite history.
Offline test results do not establish a live Telegram demo, container behavior
or successful remote CI for a pushed revision.

For focused exposure and persistence checks in an activated Python 3.12
environment, run:

```text
python -m pytest tests/bot/test_assessment.py tests/bot/test_handlers.py tests/bot/test_dispatch.py tests/bot/test_exposure.py tests/bot/test_messages.py -q
python -m pytest tests/core/test_assessment_service.py tests/core/test_data_core.py tests/core/test_summary.py tests/core/test_io_core.py tests/core/test_sqlite_storage.py tests/core/test_storage_factory.py tests/core/test_storage_migration.py -q
```

The existing CI and Docker configurations use Python 3.14; the local project target
is Python 3.12. Observe a successful CI run for the matching pushed revision and
the [offline Telegram container command](#run-docker-with-persistent-reports)
separately before claiming either passes. Local Docker and `gh` were unavailable
and WSL was not installed at the exposure documentation checkpoint. The preceding
local Python 3.12 full-suite run recorded 1630 passed, 18 skipped and one unchanged
Windows Gmail permission failure (`0600` expected, `0666` observed); it was not a
clean full-suite pass or a container/remote CI result.

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

### CLI menu options

The CLI provides two separate methods for importing `.eml` email files:

- **Option 2 — Import the newest emails from your saved folder:** Opens the configured email folder and lists available `.eml` files, with the newest files shown first. Users can select which email to import.
- **Option 3 — Upload an .eml in a browser:** Opens a local browser upload workflow, allowing users to select and upload an `.eml` file without navigating through the saved folder.

For manual message entry (Option 1), users can enter multiple lines of text. Type `END` on its own line to finish entering the message. Blank lines within the message are preserved.

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
docker run --rm --network none --user 65534:65534 --workdir /tmp phishreport-telegram python -m pytest --rootdir=/app /app/tests -p no:cacheprovider
```

To see both backend parameter IDs and exercise the storage-specific failures:

```text
python -m pytest -v tests/core/test_data_core.py tests/core/test_sqlite_storage.py tests/core/test_storage_factory.py tests/core/test_storage_migration.py
docker run --rm --network none --user 65534:65534 --workdir /tmp phishreport-telegram python -m pytest --rootdir=/app -v /app/tests/core/test_data_core.py /app/tests/core/test_sqlite_storage.py /app/tests/core/test_storage_factory.py /app/tests/core/test_storage_migration.py -p no:cacheprovider
```

CI runs the full container suite as UID/GID `65534:65534` from `/tmp`, so its
temporary files are writable and permission tests execute without root access.
`--rootdir=/app` includes the shared `/app/conftest.py` fixtures; the image supplies
`PYTHONPATH=/app` for package imports.
The shared fixture runs against `JsonReportStorage` and `SqliteReportStorage`.
Rollback tests fail an insert or commit and then read the original history.
Genuine directory-permission checks require POSIX permissions and an unprivileged
user; they skip on Windows or when permissions can be bypassed. Run these checks
under a non-root Linux user before claiming permission-denial coverage. The
existing Gmail mode-`0600` assertion also requires POSIX semantics.

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
