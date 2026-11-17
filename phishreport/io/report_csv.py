"""Write selected report rows to a new CSV file or an in-memory stream."""

import csv
import io
from collections.abc import Iterable
from pathlib import Path
from typing import TextIO

from phishreport.model import Report

CSV_COLUMNS = ("assessment_id", "channel", "priority", "score", "message")
_FORMULA_STARTS = ("=", "+", "-", "@", "\uff1d", "\uff0b", "\uff0d", "\uff20")


class ReportExportError(Exception):
    """A report CSV could not be created or written."""


class ReportCsv:
    """Write report records as CSV to a stream, memory or a new file."""

    @staticmethod
    def _spreadsheet_text(value: str | None) -> str | None:
        """Prefix formula-like text with an apostrophe before CSV quoting."""
        if value and (
            value.lstrip(" ").startswith(("\t", "\r", "\n"))
            or value.lstrip().startswith(_FORMULA_STARTS)
        ):
            return "'" + value
        return value

    @staticmethod
    def _csv_row(record: dict) -> tuple[str | int | float | None, ...]:
        report = Report(record)
        result = report.result
        return (
            ReportCsv._spreadsheet_text(report.assessment_id),
            ReportCsv._spreadsheet_text(report.channel),
            ReportCsv._spreadsheet_text(result.priority if result is not None else None),
            result.score if result is not None else None,
            ReportCsv._spreadsheet_text(report.message),
        )

    @staticmethod
    def write(stream: TextIO, records: Iterable[dict]) -> None:
        """Write the shared header and ordered rows to any text stream."""
        writer = csv.writer(stream)
        writer.writerow(CSV_COLUMNS)
        writer.writerows(ReportCsv._csv_row(record) for record in records)

    @staticmethod
    def to_bytes(records: Iterable[dict]) -> bytes:
        """Build the same CSV in memory for transports that send a document."""
        stream = io.StringIO(newline="")
        ReportCsv.write(stream, records)
        return stream.getvalue().encode("utf-8")

    @staticmethod
    def export(destination: str | Path, records: Iterable[dict]) -> None:
        """Write the ordered rows to a new UTF-8 CSV, with a header even if empty."""
        path = Path(destination)
        created = False
        try:
            with path.open("x", encoding="utf-8", newline="") as stream:
                created = True
                ReportCsv.write(stream, records)
        except BaseException as error:
            if created:
                try:
                    path.unlink(missing_ok=True)
                except OSError as cleanup_error:
                    error.add_note(f"Could not remove the incomplete CSV: {cleanup_error}")
            if isinstance(error, (OSError, ValueError, csv.Error)):
                raise ReportExportError("Could not write the report CSV.") from error
            raise
