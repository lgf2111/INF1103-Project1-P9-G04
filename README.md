# PhishReport

[![CI](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml/badge.svg)](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml)

PhishReport is a procedural Python CLI application that helps users assess suspicious emails, SMS and chat messages. It uses the Groq API to identify indicators, applies rule-based scoring based on the findings and reported user actions, and provides a priority level and recommended response steps. Assessments are saved locally as JSON.

This repository contains the Phase 1 coursework application. **A LOW-priority result does not guarantee that a message is safe.**

## Project layout

| Path | Purpose |
| --- | --- |
| `app/io_manager.py` | Collect input and display results. |
| `app/ai_manager.py` | Request and validate AI findings. |
| `app/logic_manager.py` | Apply assessment rules, scoring and routing. |
| `app/data_manager.py` | Save, load and query JSON reports. |
| `app/main.py` | Connect the managers and run the menu. |
| `app/ai_prompts.py` | Define the AI assessment instructions. |
| `app/email_html.py` | Convert HTML email content to safe text. |
| `app/local_settings.py` | Manage local preferences. |
| `app/logging_setup.py` | Configure diagnostic logs. |
| `app/web_upload.py` | Handle browser-based `.eml` uploads. |
| `tests/test_logic_manager.py` | Offline logic tests. |
| `tests/test_application.py` | Application tests and feature showcase. |
| `tests/fixtures/` | Public sample emails for testing. |
| `conftest.py` | Shared pytest configuration. |

## Set up

Use **Python 3.12** to match the CI and Docker environment. Run the following commands from the repository root.

**Windows PowerShell**

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

**macOS or Linux**

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
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
python app/main.py
```

You can manually check a suspicious message, import or upload an `.eml` email, and view saved reports. New assessments require a valid response from the Groq API.

Run the automated tests:

```bash
python -m pytest
```

Run a specific test suite or the feature showcase:

```bash
python -m pytest tests/test_logic_manager.py -q
python -m pytest tests/test_application.py -q
python -m pytest tests/test_application.py -m demo -v
```

The README currently documents **640 test cases** (including parameter variations): 72 logic tests and 568 application tests, of which 12 are showcase cases. The tests mock external AI requests; they do not measure live-model detection accuracy.

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

With Docker running and `.env` configured, use **Git Bash** on Windows (or Bash on macOS/Linux):

```bash
./docker.sh build
./docker.sh test
./docker.sh run
```

Docker keeps reports, settings and logs in the host project's `.phishreport-data/` directory so they remain available between runs. The helper also mounts the project's `emails/` directory for local `.eml` imports and makes the browser uploader available at `http://localhost:8000`.

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
