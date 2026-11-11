"""Explicit, atomic migration of JSON history to SQLite."""

import json
import os
import sqlite3
from pathlib import Path

from .json_storage import JsonReportStorage
from .sqlite_storage import SqliteReportStorage


def migrate_json_to_sqlite(
    source: str | os.PathLike[str], target: str | os.PathLike[str]
) -> int:
    """Populate empty SQLite history and return the number of imported records.

    An identical destination returns zero; different nonempty history is rejected.
    The source must exist and remains unchanged. Stop application writers before
    migrating: the JSON source has no cross-process locking contract.
    """
    source_path, target_path = Path(source), Path(target)
    if source_path.resolve() == target_path.resolve() or (
        target_path.exists() and source_path.samefile(target_path)
    ):
        raise ValueError("Migration source and destination must be distinct files.")

    # Open directly: the regular JSON reader treats a missing source as empty.
    try:
        with source_path.open(encoding="utf-8") as stream:
            records = json.load(
                stream,
                object_pairs_hook=JsonReportStorage._unique_fields,
                parse_constant=JsonReportStorage._invalid_constant,
            )
        if not isinstance(records, list):
            raise ValueError("Local report history must be a list.")
        if any(not isinstance(record, dict) for record in records):
            raise ValueError("Stored reports must be objects.")
        # Sorting fields permits harmless whitespace/key-order differences while
        # preserving JSON types (Python equality considers True and 1 equal).
        payloads = [
            json.dumps(record, ensure_ascii=False, allow_nan=False, sort_keys=True)
            for record in records
        ]
        for payload in payloads:
            payload.encode("utf-8")
    except (UnicodeError, RecursionError) as error:
        raise ValueError("Migration source contains malformed JSON text.") from error

    existed = target_path.exists()
    storage = SqliteReportStorage(target_path)
    connection = None
    primary_error = None
    try:
        connection = storage._connect()
        if not existed:
            # Match the writer's first-failure recovery: leave readable empty
            # history when the subsequent record transaction fails.
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

        connection.text_factory = bytes
        current_payloads = []
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
            normalized = json.dumps(
                record, ensure_ascii=False, allow_nan=False, sort_keys=True
            )
            normalized.encode("utf-8")
            current_payloads.append(normalized)
        if current_payloads == payloads:
            connection.execute("COMMIT")
            return 0
        if current_payloads:
            raise ValueError("Migration destination contains different report history.")
        for position, payload in enumerate(payloads):
            connection.execute(
                "INSERT INTO records(position, payload) VALUES (?, ?)",
                (position, payload),
            )
        connection.execute("COMMIT")
        return len(payloads)
    except BaseException as error:
        primary_error = error
        if isinstance(error, sqlite3.Error):
            primary_code = getattr(error, "sqlite_errorcode", 0) & 0xFF
            if primary_code in (sqlite3.SQLITE_CORRUPT, sqlite3.SQLITE_NOTADB):
                primary_error = ValueError(f"Malformed SQLite database: {target_path}")
            else:
                primary_error = OSError(f"Cannot migrate SQLite database: {target_path}")
        elif isinstance(error, (UnicodeError, RecursionError)):
            primary_error = ValueError("SQLite report payload is malformed.")
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
                        f"Cannot close SQLite database: {target_path}"
                    ) from cleanup_error
                primary_error.add_note(f"SQLite connection cleanup failed: {cleanup_error}")
