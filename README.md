# PhishReport

[![CI](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml/badge.svg)](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml)

PhishReport is a Python application with a CLI and a PySide desktop GUI under development. The app assesses suspicious emails, SMS and chat messages using the Groq API and rule-based scoring, then provides a priority level and recommended response steps. Assessments are saved locally as JSON.

**A LOW-priority result does not guarantee that a message is safe.**

## Project layout

| Path | Purpose |
| --- | --- |
| `app_cli/io_manager.py` | Compatibility functions for the I/O manager. |
| `app_cli/io_core/` | Console adapter, input coordinator, email parsing, folder selection and report presentation. |
| `app_cli/ai_manager.py` | Compatibility functions for AI prompting, requests and validation. |
| `app_cli/ai_core/` | AI assessment coordinator, prompt builder, completion client and response validator. |
| `app_cli/logic_manager.py` | Apply assessment rules, scoring and routing. |
| `app_cli/data_manager.py` | Save, load and query JSON reports. |
| `app_cli/main.py` | Compose the four managers and run the CLI through `PhishReportApp`. |
| `app_cli/ai_prompts.py` | Define the AI assessment instructions. |
| `app_cli/email_html.py` | Convert HTML email content to safe text. |
| `app_cli/local_settings.py` | Manage local preferences. |
| `app_cli/logging_setup.py` | Configure diagnostic logs. |
| `app_cli/web_upload.py` | Handle browser-based `.eml` uploads. |
| `app_gui/` | PySide desktop interface, authentication prototype and UI modules. |
| `docs/` | Organized guides, teammate handoffs, and project references. |
| `requirements.txt` | Shared dependencies for the CLI, GUI, and tests. |
| `tests/test_logic_manager.py` | Offline logic tests. |
| `tests/test_ai_core.py` | Offline assessment coordinator tests. |
| `tests/test_io_core.py` | Offline tests for input routes, email parsing, folder selection and presentation. |
| `tests/test_application.py` | Application tests and feature showcase. |
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
uv run --python 3.14 --no-project --with-requirements requirements.txt python app_cli/main.py
```

You can manually check a suspicious message, import or upload an `.eml` email, and view saved reports. New assessments require a valid response from the Groq API.

### Desktop authentication GUI

The Python desktop GUI is being migrated to the primary interface while the CLI remains available during the transition. The target is one desktop process: GUI screens call shared Python services in `app_cli/` directly, with Qt workers for slow operations—not a second assessment server. See the [frontend handoff](docs/handoffs/FRONTEND_HANDOFF.md) and [backend handoff](docs/handoffs/BACKEND_HANDOFF.md) for team ownership and the proposed service contract.

The [frontend handoff](docs/handoffs/FRONTEND_HANDOFF.md) ([HTML](docs/handoffs/FRONTEND_HANDOFF.html)) describes the planned assessment and saved-report screens. The [backend handoff](docs/handoffs/BACKEND_HANDOFF.md) ([HTML](docs/handoffs/BACKEND_HANDOFF.html)) describes the in-process assessment service contract. The current HTTP authentication demo is separate and does not provide assessment; the GUI service integration is not implemented yet.

```bash
uv run --python 3.14 --no-project --with-requirements requirements.txt python -m app_gui.main
```

`uv run` creates and reuses an isolated environment in uv's cache from the
shared root `requirements.txt`; it does not create a `.venv` in the repository.

To display the desktop GUI from Docker in a native host window, install an X
server (XQuartz on macOS or VcXsrv on Windows) and run `bash run.sh gui` as
described in the [GUI run guide](docs/guides/GUI_RUN_GUIDE.html). On Windows,
run the Bash commands from Git Bash or WSL. The command starts a local demo
authentication API automatically. The browser-based noVNC option remains
available as `bash run.sh gui-web`. The standard Docker image continues to run
the CLI.

Run the automated tests:

```bash
uv run --python 3.14 --no-project --with-requirements requirements.txt pytest
```

Run a specific test suite or the feature showcase:

```bash
uv run --python 3.14 --no-project --with-requirements requirements.txt pytest tests/test_logic_manager.py -q
uv run --python 3.14 --no-project --with-requirements requirements.txt pytest tests/test_io_core.py -q
uv run --python 3.14 --no-project --with-requirements requirements.txt pytest tests/test_application.py -q
uv run --python 3.14 --no-project --with-requirements requirements.txt pytest tests/test_application.py -m demo -v
```

The application suite uses fake completion clients and mocked Groq HTTP calls
to check prompt handling, retries, response validation and CLI behavior offline.
It runs without a Groq key after test dependencies are installed.

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

To try the desktop GUI in a native X11 window with its fixed demo account (no
Groq key required), install and start the host display server first:

- **macOS:** Install and start [XQuartz](https://www.xquartz.org/), enable
  **Authenticate connections** and **Allow connections from network clients**
  in XQuartz Settings → Security, then quit and restart XQuartz. The runner
  passes a temporary Xauthority cookie to the GUI container. Keep XQuartz
  access restricted to trusted local clients; do not use a blanket `xhost +`
  rule.
- **Windows:** Install and start [VcXsrv](https://sourceforge.net/projects/vcxsrv/)
  on display `0`. Allow it through Windows Firewall only on private networks.
  VcXsrv may require disabling access control for the Docker container to
  connect; use it only on a trusted network and close it after testing.

Then run from Bash (Git Bash/WSL on Windows):

```bash
bash run.sh gui
```

The application opens in an X11 window on the host. Sign in with
`demo@phishreport.test` / `phishreport-demo`. The runner starts and cleans up
the development-only demo auth API on a private Docker network. To use another
auth API, set `PHISHREPORT_API_URL` before starting the command. The default
display is `host.docker.internal:0`; override it with `PHISHREPORT_DISPLAY` if
your X server uses a different address.
If macOS reports that the display cannot be opened, verify XQuartz is
listening on TCP port 6000 (`nc -vz 127.0.0.1 6000`) and reachable from the
container as described in [`app_gui/README.md`](app_gui/README.md) and the [documentation index](docs/README.md).

If installing a host X server is not desirable, the browser-streamed mode is
still available:

```bash
bash run.sh gui-web
```

Open the printed local URL in a browser. The noVNC port is bound to
`127.0.0.1`; do not expose it publicly.

To check the required suites directly in Docker without external network access:

```bash
docker build -t phishreport .
docker run --rm --network none phishreport python -m pytest tests/test_logic_manager.py -q
docker run --rm --network none phishreport python -m pytest tests/test_application.py -q
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
