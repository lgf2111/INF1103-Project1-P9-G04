# Real email import: fix and review guide

Related issue: [#57](https://github.com/lgf2111/INF1103-Project1-P9-G04/issues/57).
This is an I/O bug fix and integration handoff, not a submission-readiness claim.

## Problem and resulting behavior

Our folder importer rejected HTML email, including the three real samples already
tracked under `emails/`. Our browser uploader followed a different path: it sent
raw MIME text after lossy UTF-8 decoding, marked the uploaded email as an included
attachment, and could not collect click/download exposure correctly.

Both routes now preserve original email bytes and use the same bounded MIME parser
before AI assessment. A supported message becomes decoded subject/body text and
untrusted sender metadata; I/O asks the same exposure questions for both routes.
The existing AI validation, business rules and persistence pipeline then run.
Malformed or unsupported input fails before AI instead of becoming a completed
assessment. Removing the API still prevents new assessments.

## Changes by boundary

- `io_manager.read_eml_bytes`: shared filesystem/browser parsing, strict transfer
  and charset decoding, original size/MIME count/depth/final-text limits.
- `io_manager.email_html`: inert HTML text plus link/form/image targets and image
  descriptions. Both plain and HTML alternatives are retained; blank alternatives
  do not block usable content. No rendering, execution or resource fetching.
- Header handling preserves forged sender text as untrusted evidence instead of
  repairing/authenticating addresses; duplicate or undecodable headers still fail.
- `misc.web_upload`: bounded multipart upload, quoted boundaries, original file
  bytes, `.eml`-only restriction, finite socket timeout and server cleanup.
  A `message/rfc822` upload label no longer turns the file into a nested object.
  Functions configure existing standard-library objects; no team-authored handler
  class is defined. Terminal instructions are displayed through I/O.
- `main.upload_file`: collect and validate the uploaded record through I/O before
  calling the existing assessment pipeline. Import, server and validation failures
  return to the menu.
- Exposure answers describe the user's actual actions. Uploading an email does
  not mean its attachment was downloaded; AI does not infer user actions.

Limits remain 2 MiB per file, 100 MIME parts, depth 32 and 50,000 final message
characters. The request allowance adds 64 KiB for multipart framing. Attachments
and embedded image content are not analyzed; image descriptions may be included.
This is an exported-file workflow, not an Outlook/mail-server integration.

## Verification and provenance

Real-data acceptance inputs came from
[`rf-peixoto/phishing_pot`](https://github.com/rf-peixoto/phishing_pot/tree/2933c0341b1248678c1e246b36d352add2edf0f1/email),
pinned at `2933c0341b1248678c1e246b36d352add2edf0f1`:
`sample-1.eml` through `sample-30.eml`, plus `sample-100.eml` and `sample-1000.eml`.
The three tracked samples match that source byte-for-byte. No extra corpus files,
private email, chat exports, credentials or local audit artifacts are added here.

On 13 October 2026:

- The complete offline regression suite passed in Docker with external networking
  disabled: **581 passed**. Ruff and patch-whitespace checks passed. Real acceptance
  data and recorded/live AI evidence below remain separately identified.
- 29/32 real files parsed on Windows and inside Docker. All accepted files had
  identical browser/folder records for identical exposure answers. The other
  three were safely rejected; see limitations below.
- Actual host-to-published-Docker HTTP upload and actual folder menu both assessed
  real sample 1 with equal saved records. A fresh container reloaded the mounted
  JSON without modifying its bytes or calling AI again. These checks replayed
  findings actually obtained from that file's live response; PostgreSQL was mocked.
- Live Groq assessments of samples 1, 2 and 3 completed with validated findings
  and local save/reload: 45/MEDIUM, 60/MEDIUM and 45/MEDIUM respectively. No shared
  database was contacted. These are response priorities, not detection accuracy.
- Sample 10's live extraction failed source validation; subsequent calls hit HTTP
  429. Those checks saved no assessment. Live results for samples 100/1000 and a
  fresh repeatability run remain unverified. No model rotation bypassed rate limits.
- New regressions use original tracked real emails under three browser MIME labels
  and real message bodies inside empty-alternative MIME wrappers. Existing offline
  unit/fault tests are retained as required by the professor; they are distinct
  from real-email acceptance evidence and do not establish detection accuracy.

Reproduce offline checks from the repository root:

```sh
docker build -t phishreport:email-review .
docker run --rm --network none phishreport:email-review pytest -q -p no:cacheprovider
docker run --rm --network none phishreport:email-review pytest -q -k 'real_tracked_email or tracked_real_email or empty_plain_alternative'
```

For manual verification, mount an email folder and a separate writable data
directory, publish port 8000 to localhost, and supply AI credentials privately.
Choose option 2 and the mounted email folder, then repeat the same file through
option 3 and the upload page. Enter identical truthful exposure answers. Check
decoded text, score/reasons/actions, JSON persistence and restart. Never follow
the phishing URLs or run attachments while checking.

On the preceding main `2e95b05`, option 2 with `emails/sample-1.eml` rejects the
HTML body before AI. The new real-data tests reproduce that supported-input gap.

## Remaining limitations and review responsibilities

- Samples 14, 28 and 30 use unsupported `multipart/form-data` email containers and
  nonstandard `Hexa` transfer encoding. They remain rejected; no decoding is guessed
  and no partial content is silently declared a complete assessment.
- AI extraction rejection, provider quota and fresh-call repeatability need separate
  AI-layer verification. Parsing success is not a guarantee of a live verdict.
- Legacy-history corruption, `route(record)`, startup configuration, storage policy,
  report reconciliation and final all-team Docker evidence are outside this patch.
- PR #58 removes obsolete input helpers. This patch deliberately retains those
  interfaces; reconcile and rerun tests if both changes merge.

I am publishing this fix with Jeremy Goh's requested co-author credit. Jeremy's
parser ownership and Bryan Lee's upload/display ownership remain intact. I propose
Bryan Lee as the independent reviewer because a co-author should not supply the
non-author approval. Review the canonical record, exposure contract, procedural
constraint and failure paths before merging. Keep #57 open until its acceptance
scope is agreed and the unknown teammate case is addressed if available; this PR
does not automatically close it or claim approval has already happened.
