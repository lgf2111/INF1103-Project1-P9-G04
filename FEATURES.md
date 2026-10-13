# Features and Contributions

This file records who built what, so everyone gets credit for their work.
Add a row when you finish a feature. Link the pull request if you can.

## Foundation contribution history

I retain the foundation contributions below as historical evidence. Their original
test count and release are not the final submission verification.

| Feature | Description | Owner | PR |
| --- | --- | --- | --- |
| Project setup & MVP wiring | Repo layout, `main.py` connecting the pipeline, and starter managers so the app runs end to end | Lee Guan Feng | early commits |
| Groq AI integration | `ai_manager` calls the Groq API (free tier), requests JSON and validates the reply | Lee Guan Feng | #4 |
| Docker | `Dockerfile` plus `docker.sh` helper (build/run/test/shell/clean) so the app runs the same on any laptop | Lee Guan Feng | #6 |
| GitHub Actions CI | `.github/workflows/ci.yml`: lint, tests and Docker build/test on every push and PR | Lee Guan Feng | #1 |
| Ruff lint in CI | Adds an automated code-style check (`ruff`) with `ruff.toml` config | Lee Guan Feng | #8 |
| No-class guard in CI | Fails the build if any `class` appears in `app/`, protecting the 100%-procedural instant-fail rule | Lee Guan Feng | #9 |
| CI status badge | Shows the pipeline status at the top of the README | Lee Guan Feng | #10 |
| Release automation | `.github/workflows/release.yml`: pushing a `v*` tag runs tests then publishes a GitHub Release with notes | Lee Guan Feng | #11 |
| Offline test suite | 24 tests across `logic_manager`, `ai_manager` and `data_manager`, all without the live API | Lee Guan Feng | #7 |
| Project docs | `README.md` (setup/run/rules guide) and this file | Lee Guan Feng | #12 |
| v1.0.0 release | First complete working, tested, containerised end-to-end release | Lee Guan Feng | tag v1.0.0 |

## Integrated work

| Contribution | Contributor(s) | Evidence |
| --- | --- | --- |
| Validated collection and email/MIME input | Jeremy Goh | PRs 19, 23, 39 |
| Result and saved-record displays | Bryan Lee | PR 22 |
| Logic and data development, agreed scoring and local-only storage | Xavier Heng / Bryan Ow | PRs 20, 64, 69; original commits identify individual work |
| AI validation and integration, real-email reliability | My AI/integration work with existing team parser contributions retained | PRs 25, 59, 68 |
| Safe optional configuration startup | My integration work | PR 65 |
| Docker directory persistence and email mounts | My deployment fix with Guan Feng / Bryan Ow co-authorship | PR 67 |
| Malformed-history recovery after local-only integration | My regression fix | PR 72 |
| Required literal manager files and submission reconciliation | My integration/compliance work | Issue 71; code 0d6834e |

I keep the original commits and PRs as the authority for authorship. Refactoring
or testing another layer does not transfer its original contribution. Current
scope and unresolved delivery gates are in ROADMAP.md.

I reviewed the complete application against Week 4 slides 32-42 in issue #74: explicit helper modules, shared input construction, clear interfaces, validated settings/picker failures and network-disabled CI tests. Original layer contributions remain credited above.

Issue #78 records the final audit: corrupt settings/history preservation and upload
configuration recovery, with regression coverage retained in two requested test
scripts. Three necessary real-email fixtures remain; obsolete demo copies and the
old import handoff are removed. Consolidating tests does not transfer their original
authors' contributions or establish instructor approval or team verification.
