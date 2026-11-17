# Documentation

- [Exception-handling matrix](exception-matrix.md) maps every failure to its typed error,
  the user-facing message, the fallback behaviour and the test that proves it.
- [Telegram run guide](../README.md#telegram-connection-mvp) covers configuration, Docker,
  and the live connection test.
- [Coursework documents](coursework/) contain the assignment and grading PDFs.

## Submission artefacts

The engineering report, the presentation deck and the captured screenshots are generated
material. They are built locally into `docs/report/` and are deliberately **not tracked by
git**, so the repository stays a code repository. `docs/report/` is listed in `.gitignore`,
and the folder ships inside the submission zip instead.

To regenerate them:

```bash
python scripts/report_assets.py                    # diagrams and OOP evidence
```

The report HTML and the deck are authored artefacts kept with the submission package, not
generated from the code.

For general setup and CLI usage, see the [root README](../README.md).
