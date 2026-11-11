"""SQLite-backed report storage."""

import os
import sqlite3
from pathlib import Path

from .storage import ReportStorage


class SqliteReportStorage(ReportStorage):
    """Store the path to a SQLite report database."""

    def __init__(self, path: str | os.PathLike[str] = "reports.sqlite3") -> None:
        self._path = Path(path)

    def _connect(self, *, readonly: bool = False) -> sqlite3.Connection:
        """Open a configured connection; the caller must close it on success.

        Readonly connections require an existing database and leave its journal
        mode and schema unchanged. Writes require WAL. Transactions are explicit.
        Malformed databases raise ValueError; SQLite I/O failures raise OSError.
        """
        connection = None
        try:
            mode = "ro" if readonly else "rwc"
            uri = f"{self._path.resolve().as_uri()}?mode={mode}"
            connection = sqlite3.connect(uri, uri=True, timeout=5.0, isolation_level=None)
            connection.execute("PRAGMA busy_timeout = 5000")
            if readonly:
                # Opening alone does not inspect the header of a corrupt file.
                connection.execute("PRAGMA schema_version").fetchone()
            else:
                journal_mode = connection.execute("PRAGMA journal_mode = WAL").fetchone()
                if journal_mode != ("wal",):
                    raise OSError(f"SQLite WAL mode is unavailable for {self._path}")
            return connection
        except BaseException as error:
            # Cancellation must release the resource just like configuration errors.
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error as cleanup_error:
                    error.add_note(f"SQLite connection cleanup failed: {cleanup_error}")
            if isinstance(error, sqlite3.Error):
                primary_code = getattr(error, "sqlite_errorcode", 0) & 0xFF
                if primary_code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
                    raise ValueError(f"Malformed SQLite database: {self._path}") from error
                raise OSError(f"Cannot open SQLite database: {self._path}") from error
            raise
