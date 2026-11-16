# Demo workflow

Ten minutes, five acts. Each act maps to something the rubric grades, so nothing is
shown twice. Run it in this order on the day.

## Pre-flight (five minutes before)

```bash
git pull
docker build -t phishreport-telegram --target telegram .
docker run --rm --network none phishreport-telegram python -m pytest -q   # proves the container is green
cp .env.example .env            # then fill GROQ_API_KEY and TELEGRAM_BOT_TOKEN
```

Have ready:
- a clean `.phishreport-data/reports.json` so history builds in front of the panel;
- the rule-outcome trace visible in results (it prints with every assessment);
- a terminal at the repo root and Telegram open on a phone beside it.

Do **not** seed history. The summary in Act 2 must count reports you created on stage.

## Act 1 — CLI assessment, trace and feedback (3 min)

`bash run.sh cli` (or the documented `uv run` command), then option **1**.

1. Paste a multi-line smishing email, ending with `END` on its own line. This shows the
   multi-line input fix and that the whole body is assessed, not the first line.
2. Point at the result: score, band, reasons, actions, and the **rule trace** — which
   rule matched and therefore why the score is what it is. That trace is the new
   feature's user-visible half.
3. Answer the feedback prompt with a category (for example "incorrect explanation").
   That writes to `feedback.json`, separate from the reports.

Grades: AI-centred pipeline, rule engine, new feature (trace + feedback), input
handling.

## Act 2 — history, filter and summary (2 min)

Stay in the CLI.

1. Option **4** (view saved reports) — the report from Act 1 is there.
2. Option **2** (import the newest emails from your saved folder) — pick one `.eml`.
   Second assessment, no retyping.
3. Option **5** (summarize) and filter by priority, then by channel. The counters move
   because of the two reports you just made.

Grades: DataManager query and validation, `ReportFilter`/`SummaryMetric`,
persistence across runs.

## Act 3 — Telegram as the GUI (3 min)

Start the bot (`bash run.sh telegram`), then on the phone:

1. `/start` — welcome and the connection check button. Tap it: "Connection check
   passed."
2. Send a phishing text **containing a link**. The bot replies with a provisional
   assessment (capped at MEDIUM), then asks the exposure question with buttons.
3. Tap **clicked**. The same reply is edited in place to **HIGH / 80** and the reasons
   now say you reported clicking. No second AI call happened — say that out loud.
4. Send a second message, tap **password**. Score 90, and the checklist starts with
   "change the affected password".
5. `/status` shows the session and the saved-report count; `/help` lists commands.

This is the advanced deliverable: inline keyboards, rendered cards, multi-select
exposure, shared command objects with the CLI.

## Act 4 — DevOps evidence (1.5 min)

1. Open the repository's Actions tab on the merged commit: lint, test, and the docker job
   that runs the suite inside the image.
2. Switch storage in front of the panel:

   ```bash
   PHISHREPORT_STORAGE=sqlite PHISHREPORT_REPORTS_PATH=/tmp/demo.json \
     python -m phishreport.cli
   ```

   The SQLite database is created as a sibling (`/tmp/demo.sqlite3`). Save one report,
   quit, rerun with the same variables, and show it still loads. Same commands,
   different backend — that is the Liskov evidence made visible. (If `/tmp/demo.json`
   already exists, the factory refuses two backends on the same file; point at a fresh
   name instead.)
3. Mention the test count from the run you just executed, not from memory.

## Act 5 — design evidence (1 min)

Show, in this order, and keep each to one sentence:

1. `docs/report/class-diagram.mmd` — four managers, two ABCs, two storage backends.
2. `docs/report/oop-evidence.md` — one file:line per mandatory concept.
3. `docs/exception-matrix.md` — every failure, its typed error, its user message, its test.

## Questions to expect

- **Why rules on top of the AI?** The AI extracts findings; the score must be
  deterministic and auditable, so rules decide the band. Every AI reply is validated
  before a rule sees it.
- **Where is the polymorphism?** `PriorityRuleEngine` holds eight rule objects and calls
  the same two methods on each; adding a rule is a new subclass.
- **Where is Liskov, really?** The storage contract suite runs unchanged against JSON and
  SQLite. Show it with the storage switch.
- **Why is Telegram a GUI?** Inline keyboards, callback queries and rendered cards are a
  graphical interaction surface over the same core as the CLI. Show the exposure buttons.
- **What if the AI is down?** Typed failure, safe message, nothing saved, no verdict
  invented. The matrix row names the test.
- **Concurrency?** AI calls run off the bot's event loop; saves are serialised by a lock;
  storage is single-writer by design and documented as such.
- **Privacy?** Message bodies stay local, logs exclude them, the Gmail app password is
  stored 0600 and deleted on unlink.

## Failure drills

- **AI rate-limited or offline:** show the typed message rather than retrying on stage.
  The point is the handling, not a lucky call.
- **Bot is slow:** the provisional assessment already answered the user; the exposure
  buttons arrive after. Do not restart the bot mid-demo.
- **History file missing:** that is not an error — the first save creates it. Say so.

## Four-minute cut

Act 1 (one message + trace) → Act 3 (link, clicked, HIGH) → Act 4 (CI tab + storage
switch) → Act 5 (class diagram). Drop the folder import, the summary filter and the
feedback prompt.

## Board state note

Two Phase 2 tasks still read "In progress" although their code is on `main`
(`phishreport/model.py` with `phishreport/errors.py`, and the renderer consolidation in
`phishreport/io/render.py`). The third, "pull report query and export out of the CLI
app", has not been built — do not claim export during the demo.
