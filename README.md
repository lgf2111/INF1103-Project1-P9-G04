# PhishReport

[![CI](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml/badge.svg)](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml)

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

### Import an email

Choose **2. Import an email (.eml file)** from the main menu. On first use,
choose the folder containing your emails, then select a listed file. The folder
is saved for later imports. Then answer the link, file and action questions.
Choose **1. Check a new message (Manual Input)** to type an Email, SMS or Chat message. We include the
subject and every inline plain-text body part in the text sent for assessment.
Valid Base64, quoted-printable and declared character sets are decoded without
silently replacing invalid characters. Missing sender/subject headers are allowed;
duplicate or malformed sender/subject headers are rejected.

We support plain-text bodies, including nested mixed, alternative and related
containers whose inline parts are all plain text. HTML bodies (including a
plain-text/HTML alternative) and other inline content are rejected instead of
assessing only part of the message. Attachments are excluded from assessment.
For unsupported emails, restart the input flow and choose manual input to provide
the relevant message text. We still ask separately about links, files, clicks,
downloads and password/code disclosure; these actions are never inferred.

Imports are limited to regular files of 2 MiB, 100 MIME parts, 32 nesting levels
and 50,000 final message characters (including the subject). Invalid imports
display an error and ask for another file. These limits are our implementation
choices, not additional coursework requirements.

## Run Docker with persistent reports

I create `.env` as described above, start Docker, then build, test and run:

```bash
./docker.sh build
./docker.sh test
./docker.sh run
```

On Windows I use **Git Bash**, or WSL with Docker integration enabled. On macOS
and Linux I use Bash; if needed I first run `chmod +x docker.sh`. The helper
resolves paths from its own project directory, so I can also invoke it from
another working directory. Its test command disables external networking.

My Docker reports, settings and logs are stored in **`.phishreport-data/`** on
the host. The helper mounts that directory at `/data`, sets it as the working
directory and launches `/app/app/main.py`. I mount the directory rather than
`reports.json` itself because the data manager saves by atomically replacing the
file; replacing an individually bind-mounted file fails in Docker.

On first setup I copy existing root `reports.json`, `.phishreport_config.json`
and logs into the data directory if their destinations do not already exist.
Later runs preserve the newer destination files. The original files remain
untouched; this is a one-time copy, not ongoing synchronization. I do not reset
corrupt history. After migration I use `.phishreport-data/reports.json` for my
Docker history; running host Python from the repository root still uses the
separate root `reports.json`.

### Email folder inside Docker

I select **2. Import an email** and enter **`/emails`** when asked for the email
folder. The helper mounts my project's `emails/` directory there read-only. The
folder picker then remembers this container path across runs. A saved Windows or
macOS host path is not automatically available inside a container; if old copied
settings point to an unavailable path, I enter `/emails` when prompted again.

To use another folder, I set `PHISHREPORT_EMAIL_DIR` for the run. Relative paths
are resolved against the project, and spaces are supported:

```bash
PHISHREPORT_EMAIL_DIR="Saved emails" ./docker.sh run
```

I can also use an absolute folder path, such as `/c/Users/me/Downloads/emails`
in Git Bash or `/home/me/emails` on Linux. This selects saved files; it does not
connect to a mailbox or add support for otherwise unsupported MIME formats.

The helper publishes menu option 3's upload page at
http://localhost:8000, bound to the host's loopback interface. I keep
`.phishreport-data/`, root settings and logs out of Git and the Docker image.

### Check persistence after a restart

I assess a supported real `.eml` using a configured API key, check that the app
reports no local-save failure, and quit. I then run `./docker.sh run` again and
select **4. View saved reports**. The same completed record should still exist,
and the folder picker should retain `/emails`. I record the tested commit and
results for my laptop; each teammate must verify the final submission version.

For an equivalent manual Bash run after setup, I use directory mounts and the
absolute application entry point:

```bash
docker run --rm -it -p 127.0.0.1:8000:8000 --env-file .env \
  --mount "type=bind,source=$(pwd)/.phishreport-data,target=/data" \
  --mount "type=bind,source=$(pwd)/emails,target=/emails,readonly" \
  -w /data phishreport python /app/app/main.py
```

For Git Bash I use the helper, which explicitly converts host paths and prevents
MSYS from rewriting container paths. A bare `docker run --rm ... phishreport`
without a persistent directory mount still loses container-local reports.

## Contributing

See the [proposed team workflow](ROADMAP.md#team-standards-and-task-instructions) for task issues, branch names, checks and pull request reviews.
