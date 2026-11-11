"""SQLite-backed report storage."""

import json
import os
import sqlite3
from pathlib import Path

from .json_storage import JsonReportStorage
from .storage import ReportStorage


class SqliteReportStorage(ReportStorage):
    """Store the path to a SQLite report database."""

    def __init__(self, path: str | os.PathLike[str] = "reports.sqlite3") -> None:
        self._path = Path(path)

    def read_records(self) -> list[dict]:
        """Read ordered strict JSON objects in one readonly database snapshot.

        Missing files are empty history. Existing malformed databases, schemas
        and payloads raise ValueError; operational SQLite failures raise OSError.
        Historical report fields are preserved without report-schema validation.
        """
        try:
            self._path.stat()
        except FileNotFoundError:
            return []

        connection = None
        primary_error = None
        try:
            connection = self._connect(readonly=True)
            connection.execute("BEGIN")
            table = connection.execute(
                "SELECT type FROM sqlite_master WHERE name = 'records'"
            ).fetchone()
            columns = connection.execute("PRAGMA table_xinfo(records)").fetchall()
            if table != ("table",) or [
                (column[1], column[2].upper(), column[5], column[6]) for column in columns
            ] != [("position", "INTEGER", 1, 0), ("payload", "TEXT", 0, 0)]:
                raise ValueError("SQLite report history has an incompatible schema.")
            # INTEGER PRIMARY KEY must alias the rowid. The inline DESC quirk
            # creates a separate primary-key index and permits noninteger keys.
            indexes = connection.execute("PRAGMA index_list(records)").fetchall()
            if any(index[3] == "pk" for index in indexes):
                raise ValueError("SQLite report positions must be integer rowid keys.")

            # Fetch raw TEXT bytes so malformed UTF-8 is a content error, rather
            # than sqlite3's OperationalError during automatic text decoding.
            connection.text_factory = bytes
            records = []
            for payload, payload_type in connection.execute(
                "SELECT payload, typeof(payload) FROM records ORDER BY position"
            ):
                if payload_type != b"text":
                    raise ValueError("Stored report payloads must be JSON text.")
                record = json.loads(
                    payload.decode("utf-8"),
                    object_pairs_hook=JsonReportStorage._unique_fields,
                    parse_constant=JsonReportStorage._invalid_constant,
                )
                if not isinstance(record, dict):
                    raise ValueError("Stored reports must be objects.")
                records.append(record)
            return records
        except BaseException as error:
            primary_error = error
            if isinstance(error, sqlite3.Error):
                primary_code = getattr(error, "sqlite_errorcode", 0) & 0xFF
                if primary_code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
                    primary_error = ValueError(f"Malformed SQLite database: {self._path}")
                else:
                    primary_error = OSError(f"Cannot read SQLite database: {self._path}")
                raise primary_error from error
            if isinstance(error, (UnicodeError, RecursionError)):
                primary_error = ValueError("SQLite report payload is malformed.")
                raise primary_error from error
            raise
        finally:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error as cleanup_error:
                    if primary_error is None:
                        raise OSError(
                            f"Cannot close SQLite database: {self._path}"
                        ) from cleanup_error
                    primary_error.add_note(f"SQLite connection cleanup failed: {cleanup_error}")

    def write_records(self, records: list[dict]) -> None:
        """Pre-serialize report objects, then replace them in one transaction.

        Invalid inputs never open the database. Existing schemas must match the
        read contract; insert and commit failures roll back the complete write.
        New paths receive an empty table before replacement begins, so a failed
        first replacement leaves readable empty history for subsequent retries.
        """
        if not isinstance(records, list):
            raise ValueError("Report history must be a list.")
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("Stored reports must be objects.")
        payloads = [
            json.dumps(record, ensure_ascii=False, allow_nan=False) for record in records
        ]
        # SQLite TEXT requires UTF-8; check encoding before opening any files.
        for payload in payloads:
            payload.encode("utf-8")

        existed = self._path.exists()
        connection = None
        primary_error = None
        try:
            connection = self._connect()
            if not existed:
                connection.execute(
                    "CREATE TABLE IF NOT EXISTS records("
                    "position INTEGER PRIMARY KEY, payload TEXT)"
                )
            connection.execute("BEGIN IMMEDIATE")
            table = connection.execute(
                "SELECT type FROM sqlite_master WHERE name = 'records'"
            ).fetchone()
            columns = connection.execute("PRAGMA table_xinfo(records)").fetchall()
            if table != ("table",) or [
                (column[1], column[2].upper(), column[5], column[6]) for column in columns
            ] != [("position", "INTEGER", 1, 0), ("payload", "TEXT", 0, 0)]:
                raise ValueError("SQLite report history has an incompatible schema.")
            indexes = connection.execute("PRAGMA index_list(records)").fetchall()
            if any(index[3] == "pk" for index in indexes):
                raise ValueError("SQLite report positions must be integer rowid keys.")
            connection.execute("DELETE FROM records")
            for position, payload in enumerate(payloads):
                connection.execute(
                    "INSERT INTO records(position, payload) VALUES (?, ?)",
                    (position, payload),
                )
            connection.execute("COMMIT")
        except BaseException as error:
            primary_error = error
            if isinstance(error, sqlite3.Error):
                primary_code = getattr(error, "sqlite_errorcode", 0) & 0xFF
                if primary_code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
                    primary_error = ValueError(f"Malformed SQLite database: {self._path}")
                else:
                    primary_error = OSError(f"Cannot write SQLite database: {self._path}")
            if connection is not None:
                try:
                    if connection.in_transaction:
                        connection.execute("ROLLBACK")
                except sqlite3.Error as cleanup_error:
                    primary_error.add_note(f"SQLite rollback cleanup failed: {cleanup_error}")
            if primary_error is not error:
                raise primary_error from error
            raise
        finally:
            if connection is not None:
                try:
                    connection.close()
                except sqlite3.Error as cleanup_error:
                    if primary_error is None:
                        raise OSError(
                            f"Cannot close SQLite database: {self._path}"
                        ) from cleanup_error
                    primary_error.add_note(f"SQLite connection cleanup failed: {cleanup_error}")

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
