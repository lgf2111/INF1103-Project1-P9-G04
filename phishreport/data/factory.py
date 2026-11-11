"""Select report storage from the process environment at composition time."""

import os
from pathlib import Path

from .json_storage import JsonReportStorage
from .sqlite_storage import SqliteReportStorage
from .storage import ReportStorage


def create_report_storage() -> ReportStorage:
    """Construct the selected backend without opening its storage file.

    PHISHREPORT_STORAGE defaults to json. PHISHREPORT_REPORTS_PATH specifies
    the JSON path; SQLite uses a sibling with the .sqlite3 suffix. Relative
    paths retain their operation-time working-directory behavior.
    """
    backend = os.environ.get("PHISHREPORT_STORAGE", "json")
    if backend not in ("json", "sqlite"):
        raise ValueError("PHISHREPORT_STORAGE must be json or sqlite.")

    json_path = Path(os.environ.get("PHISHREPORT_REPORTS_PATH", "reports.json"))
    if backend == "json":
        return JsonReportStorage(json_path)

    sqlite_path = json_path.with_suffix(".sqlite3")
    if sqlite_path.resolve() == json_path.resolve():
        raise ValueError("JSON and SQLite storage must use distinct paths.")
    try:
        same_file = sqlite_path.samefile(json_path)
    except FileNotFoundError:
        same_file = False
    if same_file:
        raise ValueError("JSON and SQLite storage paths alias the same file.")
    return SqliteReportStorage(sqlite_path)
