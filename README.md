# PhishReport

[![CI](https://github.com/lgf2111/phish-report/actions/workflows/ci.yml/badge.svg)](https://github.com/lgf2111/phish-report/actions/workflows/ci.yml)

PhishReport is a procedural Python CLI for checking suspicious messages. It sends each new message to the Groq API, validates the AI findings, and applies rules using those findings and the user's reported actions. It displays a priority, a rule-based score and a response checklist, then saves the assessment as JSON.

This is the Phase 1 coursework application. The current code provides a starter assessment flow; planned improvements and team decisions are in [ROADMAP.md](ROADMAP.md). A result with no clear indicators does not guarantee that a message is safe.

## Project layout

| Path | Purpose |
| --- | --- |
| `app/io_manager.py` | Collect terminal input and display results. |
| `app/ai_manager.py` | Request and validate structured AI findings. |
| `app/logic_manager.py` | Apply assessment rules, scoring and routing. |
| `app/data_manager.py` | Save, load and query JSON reports. |
| `app/main.py` | Connect the managers and run the menu. |
| `tests/` | Run offline tests with sample AI responses. |

## Set up

Use Python 3.12 to match CI and the Docker image. Run these commands from the repository root.

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

Open `.env` and set `GROQ_API_KEY` to your key from the [Groq console](https://console.groq.com):

```text
GROQ_API_KEY=your_key_here
```

A key is required for a live assessment, but not for the offline tests. Use fictional messages for testing; never enter real passwords or one-time codes.

## Run and test

```bash
python app/main.py
python -m pytest
```

The app lets you assess a message, view saved reports or quit. It writes `reports.json` in the directory from which you run it. The tests use sample AI responses and do not need network access.

## Check the Docker build

With Docker running, build the image and run the offline tests:

```bash
docker build -t phishreport .
docker run --rm phishreport pytest
```

To run the interactive application in Docker, first create `.env` as described above:

```bash
docker run --rm -it --env-file .env phishreport
```

Reports saved inside this temporary container do not persist after it exits. Persistent container storage and verification on every team laptop remain delivery tasks in the roadmap.

## Contributing

See the [proposed team workflow](ROADMAP.md#team-standards-and-task-instructions) for task issues, branch names, checks and pull request reviews.
