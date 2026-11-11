"""SQLite-backed report storage."""

import os
from pathlib import Path

from .storage import ReportStorage


class SqliteReportStorage(ReportStorage):
    """Store the path to a SQLite report database."""

    def __init__(self, path: str | os.PathLike[str] = "reports.sqlite3") -> None:
        self._path = Path(path)
