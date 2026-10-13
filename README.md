# PhishReport

[![CI](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml/badge.svg)](https://github.com/lgf2111/INF1103-Project1-P9-G04/actions/workflows/ci.yml)

PhishReport is a procedural Python CLI for checking suspicious messages. It sends each new message to the Groq API, validates the AI findings, and applies rules using those findings and the user's reported actions. It displays a priority, a rule-based score and a response checklist, then saves the assessment as JSON.

This is the Phase 1 coursework application. The current code provides an integrated assessment flow; planned improvements and team decisions are in [ROADMAP.md](ROADMAP.md). A result with no clear indicators does not guarantee that a message is safe.

## Project layout

| Path | Purpose |
| --- | --- |
| `app/io_manager.py` | Collect terminal input and display results. |
| `app/ai_manager.py` | Request and validate structured AI findings. |
| `app/logic_manager.py` | Apply assessment rules, scoring and routing. |
| `app/data_manager.py` | Save, load and query JSON reports. |
| `app/main.py` | Connect the managers and run the menu. |
| `app/ai_prompts.py` | Fixed instructions used by the AI manager. |
| `app/email_html.py` | Convert HTML to inert text without fetching resources. |
| `app/local_settings.py` | Read and write machine-specific JSON preferences. |
| `app/logging_setup.py` | Configure safe rotating diagnostic logs. |
| `app/web_upload.py` | Receive one bounded browser upload; I/O handles assessment input. |
| `tests/test_logic_manager.py` | Required offline logic tests with hardcoded AI findings. |
| `tests/test_application.py` | Automated feature showcase and preserved application regressions. |
| `tests/fixtures/` | Three essential, pinned public email fixtures; provenance included. |

## My coding practices

I follow Week 4, slides 32-42, within the Phase 1 manager requirements.
The four named manager files contain their required functions. Supporting
modules have descriptive names directly under app/; they do not replace managers.

| Lecture principle | Application in this project |
| --- | --- |
| Single responsibility | I keep input/display, API validation, scoring and report persistence in their respective managers. |
| DRY | Manual, folder and browser routes reuse one record/exposure builder and one email parser. |
| KISS | I use functions and dictionaries, with explicit helper names and no extra framework. |
| Input / process / output | main.py coordinates validated input, AI, domain rules, JSON save and display. |
| Modular programming | I keep focused functions, typed public contracts, tested commit blocks and CI. |
| Validation | I validate messages, MIME, AI schema/source, stored records, saved folder paths and logging levels before use. |
| Meaningful naming | local_settings, get_setting and save_setting describe their purpose without a generic misc package. |

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

The `.env` file is optional when settings are supplied by your shell or Docker.
Save it as UTF-8 (a UTF-8 BOM is accepted), using the existing `KEY=value` format.
Existing environment values take precedence; repeated file keys keep their first
value. Blank lines, comments and lines without `=` are ignored.

If the file cannot be read or decoded, or an assignment has an empty key or a NUL
character, startup displays a warning and continues using existing environment
settings. File settings are checked before any are applied, so an invalid or
partly read file does not leave a partial configuration behind. The warning and
its log entry contain no file contents or raw exception details. Missing API
credentials still prevent a completed assessment; this recovery does not bypass AI.

## Run and test

```bash
python app/main.py
python -m pytest tests/test_logic_manager.py -q
python -m pytest tests/test_application.py -q
```

The app lets you assess a message, view saved reports or quit. It writes `reports.json` in the directory from which you run it. The tests use sample AI responses and do not need network access.

For the concise automated feature showcase, run
`python -m pytest tests/test_application.py -k demo -v`. It exercises real public
emails through manual/folder/browser input, multi-field scoring, exposure,
uncertainty, failures and reload in a separate process. External AI HTTP is mocked;
the local upload server, managers and storage are real. This is not a live-model
demonstration or detection benchmark. The full application script retains meaningful
lifecycle regressions in named sections. `python -m pytest` runs both scripts.

The existing logic script satisfies Framework section 5.3: `evaluate()`, `score()`
and `route()`, hardcoded AI findings, multi-field rules, precedence, 35/70 boundary
values and invalid inputs, without credentials. No redundant logic runner is needed.

### Assessment policy

The first matching rule wins; every new assessment requires valid AI findings first.

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

HIGH starts at 70 and MEDIUM at 35. Scores express response policy, not probability.
Source checks validate returned contact syntax and ordered occurrences in the
message; they do not establish completeness, sender identity or model truth.
Identical input/findings produce identical rule results. Temperature zero does not
guarantee identical fresh API findings. Instructor interpretation of repeatability
and API scope for saved-history reads remains pending.

### Import an email

Choose **2. Import an email (.eml file)**, enter the folder containing your
exported `.eml` files on first use, then select a file. The folder is remembered
locally; `m` lists more files and `c` cancels selection. This reads exported files,
not a live Outlook mailbox. In Docker, mount the folder and enter its container
path (for example, `/emails`). Choose **3. Upload an email (.eml file)** to
upload an `.eml` file through the browser. Both email routes use the same
MIME parser, subject/sender handling and exposure questions.

Choose **1. Check a new message (Manual Input)** to type an Email, SMS or Chat
message. We include the subject and all inline plain-text/HTML body representations
in the text sent for assessment, so differing HTML content is not silently omitted.
Valid Base64, quoted-printable and declared character sets are decoded without
silently replacing invalid characters. Missing sender/subject headers are allowed;
duplicate or undecodable sender/subject headers are rejected. A forged or malformed
sender address is preserved as untrusted text rather than repaired or authenticated.

We support plain-text and HTML bodies in nested mixed, alternative and related
containers. HTML is converted to inert text with link/form targets and image
descriptions retained; scripts/styles are excluded, resources are never fetched,
and HTML is never rendered or executed. Embedded images and attachments
are excluded from content analysis. Other unsupported inline body types are rejected.
For unsupported emails, restart the input flow and choose manual input to provide
the relevant message text. We still ask separately about links, files, clicks,
downloads and password/code disclosure; these actions are never inferred.

Imports are limited to regular files of 2 MiB, 100 MIME parts, 32 nesting levels
and 50,000 final message characters (including the subject). Browser uploads
reject all other types with: "Only .eml email files are supported. Images and
attachments are not analysed." Oversized browser uploads return HTTP 413;
format/type errors return HTTP 400. Invalid imports
display an error and ask for another file. These limits are our implementation
choices, not additional coursework requirements.

The browser uploader also limits requests and preserves original file bytes.
Uploading the email itself does not mean a user downloaded an attachment in it.
We still ask about actual clicks, attachment downloads and disclosure; the AI
cannot infer those actions from email content.

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

### Local history and recovery

I save new assessments locally as schema version 2: the channel, original
message and explained result. No shared database is needed. Supported older
records remain readable without manufacturing missing fields.

Missing history starts empty. Unreadable, malformed JSON or invalid stored
field types are logged and handled without crashing the menu. The original
file is preserved; saving refuses to overwrite unreadable or corrupt history.
I back up and inspect that file before correcting it, rather than resetting it
silently. An assessment whose save fails is displayed with a save warning;
it is different from an AI failure, which produces no completed assessment.

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

The Docker helper creates an empty local `emails/` directory when the default
folder is needed. Put exported messages there or select another folder; personal
imports are excluded from Git and the Docker image.
For a real-example demonstration, use
`PHISHREPORT_EMAIL_DIR="tests/fixtures" ./docker.sh run` in Bash. These three public
fixtures are necessary offline regression dependencies; their source and purpose
are documented in `tests/fixtures/README.md`.

The helper publishes menu option 3's upload page at
http://localhost:8000, bound to the host's loopback interface. I keep
`.phishreport-data/`, root settings and logs out of Git and the Docker image.

`UPLOAD_PORT` defaults to 8000. Invalid text or out-of-range values fail the upload
option safely. Keep the default with the Docker helper, which publishes port 8000.
Corrupt settings are preserved; a folder can still be used for the current selection
if its preference cannot be saved. Valid updates retain unrelated keys and replace
the settings file atomically.

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

Verify the deliverables without external networking:

```bash
docker build -t phishreport .
docker run --rm --network none phishreport python -m pytest tests/test_logic_manager.py -q
docker run --rm --network none phishreport python -m pytest tests/test_application.py -q
docker run --rm --network none phishreport python -m pytest tests/test_application.py -k demo -v
```

## Submission documents and remaining gates

Submission branch: `main`. Deadline: **14 October 2026, 23:59 Singapore time**.
The report, current scope statement and release checklist are maintained privately
in `.local/submission/` for separate delivery, excluded from Git and Docker. The
supplied course instruction lists the report and approved statement with the
complete project repository; acceptance of separate delivery must be confirmed.
The current statement has no approval evidence. Approval/Initial Details receipt,
invitations/member clones, every member's final Docker checks, rehearsal and
submission receipts remain missing. [ROADMAP.md](ROADMAP.md) records G1-G8 and the normal review workflow.

## Contributing

See the [proposed team workflow](ROADMAP.md#team-standards-and-task-instructions) for task issues, branch names, checks and pull request reviews.
