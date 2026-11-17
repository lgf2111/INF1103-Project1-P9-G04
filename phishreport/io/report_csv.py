"""Write selected report rows to a new CSV file."""

import csv
from collections.abc import Iterable
from pathlib import Path

from phishreport.model import Report

CSV_COLUMNS = ("assessment_id", "channel", "priority", "score", "message")
_FORMULA_STARTS = ("=", "+", "-", "@", "\uff1d", "\uff0b", "\uff0d", "\uff20")


class ReportExportError(Exception):
    """A report CSV could not be created or written."""


def _spreadsheet_text(value: str | None) -> str | None:
    """Prefix formula-like text with an apostrophe before CSV quoting."""
    if value and (
        value.lstrip(" ").startswith(("\t", "\r", "\n"))
        or value.lstrip().startswith(_FORMULA_STARTS)
    ):
        return "'" + value
    return value


def _csv_row(record: dict) -> tuple[str | int | float | None, ...]:
    report = Report(record)
    result = report.result
    return (
        _spreadsheet_text(report.assessment_id),
        _spreadsheet_text(report.channel),
        _spreadsheet_text(result.priority if result is not None else None),
        result.score if result is not None else None,
        _spreadsheet_text(report.message),
    )


def export_reports_csv(destination: str | Path, records: Iterable[dict]) -> None:
    """Write the ordered rows to a new UTF-8 CSV, with a header even if empty."""
    path = Path(destination)
    created = False
    try:
        with path.open("x", encoding="utf-8", newline="") as stream:
            created = True
            writer = csv.writer(stream)
            writer.writerow(CSV_COLUMNS)
            writer.writerows(_csv_row(record) for record in records)
    except BaseException as error:
        if created:
            try:
                path.unlink(missing_ok=True)
            except OSError as cleanup_error:
                error.add_note(f"Could not remove the incomplete CSV: {cleanup_error}")
        if isinstance(error, (OSError, ValueError, csv.Error)):
            raise ReportExportError("Could not write the report CSV.") from error
        raise
