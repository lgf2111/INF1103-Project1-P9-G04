# data_manager.py
# Saves reports locally and in PostgreSQL. OWNER: Pair C.

import json
import os
import tempfile

import psycopg
from psycopg.rows import dict_row

FILE = "reports.json"


def _ensure_schema(cursor):
    cursor.execute(
        "CREATE TABLE IF NOT EXISTS reports ("
        "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
        "channel TEXT NOT NULL, "
        "sender TEXT, "
        "message TEXT NOT NULL, "
        "link TEXT, "
        "file_name TEXT, "
        "details JSONB NOT NULL, "
        "score INTEGER, "
        "priority TEXT)"
    )
    cursor.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS score INTEGER")
    cursor.execute("ALTER TABLE reports ADD COLUMN IF NOT EXISTS priority TEXT")


LEGACY_FIELDS = {"channel", "sender", "message", "link", "file_name", "details",
                 "score", "priority"}
INPUT_FIELDS = {"channel", "sender", "message", "has_link", "link", "has_file",
                "file_name", "clicked", "downloaded", "submitted_category"}


def _validate_report(record):
    """Validate stored structure without inventing missing legacy data or scoring."""
    if not isinstance(record, dict):
        raise ValueError("Stored reports must be objects.")
    if "schema_version" not in record:
        return record  # Older local records retain their original fields.
    if type(record["schema_version"]) is not int or record["schema_version"] != 1:
        raise ValueError("Unsupported report version.")
    if set(record) != INPUT_FIELDS | {"schema_version", "ai", "result"}:
        raise ValueError("Incomplete versioned report.")
    if not isinstance(record["channel"], str):
        raise ValueError("Invalid report channel.")
    if not isinstance(record["message"], str) or not record["message"].strip():
        raise ValueError("Invalid report message.")
    for key in ("sender", "link", "file_name"):
        if record[key] is not None and not isinstance(record[key], str):
            raise ValueError("Invalid report metadata.")
    for key in ("has_link", "has_file", "clicked", "downloaded"):
        if type(record[key]) is not bool:
            raise ValueError("Invalid reported action.")
    if record["submitted_category"] not in (None, "password", "otp"):
        raise ValueError("Invalid submitted category.")
    ai = record["ai"]
    findings = {"credential_request", "suspicious", "insufficient_context"}
    if not isinstance(ai, dict) or set(ai) != findings | {"details"}:
        raise ValueError("Invalid stored AI findings.")
    if any(type(ai[key]) is not bool for key in findings):
        raise ValueError("Invalid stored AI finding types.")
    details = ai["details"]
    if not isinstance(details, dict) or set(details) != {
        "emails", "phone_numbers", "ip_addresses"
    }:
        raise ValueError("Invalid stored extraction.")
    result = record["result"]
    if not isinstance(result, dict) or set(result) != {"score", "priority", "reasons", "checklist"}:
        raise ValueError("Invalid stored assessment.")
    if type(result["score"]) is not int or not 0 <= result["score"] <= 100:
        raise ValueError("Invalid stored score.")
    if result["priority"] not in ("LOW", "MEDIUM", "HIGH"):
        raise ValueError("Invalid stored priority.")
    for values in [*details.values(), result["reasons"], result["checklist"]]:
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError("Invalid stored text lists.")
    return record


def _database_record(record):
    """Adapt complete records to the existing eight-column PostgreSQL schema."""
    _validate_report(record)
    if "schema_version" not in record:
        if set(record) != LEGACY_FIELDS:
            raise ValueError("Legacy database reports require the eight agreed fields.")
        return record
    return {**{key: record[key] for key in ("channel", "sender", "message", "link", "file_name")},
            "details": {"schema_version": 1, "record": record},
            "score": record["result"]["score"], "priority": record["result"]["priority"]}


def _restore_record(row):
    """Recover complete JSONB payloads; leave old database rows unchanged."""
    if not isinstance(row, dict) or set(row) != LEGACY_FIELDS:
        raise ValueError("Invalid database report.")
    payload = row["details"]
    if not isinstance(payload, dict):
        raise ValueError("Invalid database details.")
    if "schema_version" not in payload:
        return row
    if set(payload) != {"schema_version", "record"} or type(payload["schema_version"]) is not int:
        raise ValueError("Invalid database payload.")
    if payload["schema_version"] != 1:
        raise ValueError("Unsupported database payload version.")
    record = _validate_report(payload["record"])
    if "schema_version" not in record or _database_record(record) != row:
        raise ValueError("Database payload does not match report columns.")
    return record


def save(record):
    """Atomically append locally before optional database upload.

    ValueError/OSError means no successful local save or database attempt.
    RuntimeError means local save succeeded but PostgreSQL upload failed.
    Single-process CLI only: concurrent writers are not supported.
    """
    _database_record(record)  # Reject invalid new records before touching history.
    records = load()
    records.append(record)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=os.path.dirname(os.path.abspath(FILE)),
            suffix=".tmp", delete=False,
        ) as stream:
            temporary = stream.name
            json.dump(records, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, FILE)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)
    upload([record])


def upload(records: list[dict]) -> int:
    """Insert complete or legacy reports into eight existing PostgreSQL columns.

    Creates the reports table if absent and inserts the batch in one transaction.
    Returns the number inserted. Repeating an upload inserts another copy.

    Raises:
        ValueError: If a versioned report is invalid or a legacy report lacks eight fields.
        RuntimeError: If configuration is missing or the database operation fails.
    """
    if not isinstance(records, list):
        raise ValueError("Reports must be a list.")
    database_records = [_database_record(record) for record in records]

    # Read configuration after main has loaded .env; never include it in errors.
    database_url = os.environ.get("DATABASE_URL", "").strip().strip("\"'")
    if not database_url:
        raise RuntimeError("Set DATABASE_URL before saving to PostgreSQL.")

    try:
        # The connection context commits on success and rolls back on failure.
        with psycopg.connect(database_url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                _ensure_schema(cursor)
                # Bind report values separately from SQL, including nested details.
                cursor.executemany(
                    "INSERT INTO reports "
                    "(channel, sender, message, link, file_name, details, score, priority) "
                    "VALUES (%s, %s, %s, %s, %s, %s::jsonb, %s, %s)",
                    [
                        (
                            record["channel"],
                            record["sender"],
                            record["message"],
                            record["link"],
                            record["file_name"],
                            json.dumps(record["details"]),
                            record["score"],
                            record["priority"],
                        )
                        for record in database_records
                    ],
                )
    except psycopg.Error as error:
        raise RuntimeError("Could not save reports to PostgreSQL.") from error

    return len(records)


def fetch() -> list[dict]:
    """Read complete/legacy reports from the existing columns in insertion order.

    Returns:
        Complete versioned records or unchanged legacy eight-field records.

    Raises:
        RuntimeError: If configuration is missing or the database read fails.
    """
    # Read current settings without revealing the connection URL in errors.
    database_url = os.environ.get("DATABASE_URL", "").strip().strip("\"'")
    if not database_url:
        raise RuntimeError("Set DATABASE_URL before viewing PostgreSQL reports.")

    try:
        with psycopg.connect(
            database_url, connect_timeout=10, row_factory=dict_row
        ) as connection:
            with connection.cursor() as cursor:
                _ensure_schema(cursor)
                # JSONB details are decoded by the driver into Python dictionaries.
                cursor.execute(
                    "SELECT channel, sender, message, link, file_name, details, "
                    "score, priority "
                    "FROM reports ORDER BY id"
                )
                return [_restore_record(row) for row in cursor.fetchall()]
    except psycopg.Error as error:
        raise RuntimeError("Could not load reports from PostgreSQL.") from error


def load():
    """Missing history is empty; unreadable/malformed history must not be overwritten."""
    try:
        with open(FILE, encoding="utf-8") as stream:
            records = json.load(stream)
    except FileNotFoundError:
        return []
    except (json.JSONDecodeError, UnicodeError) as error:
        raise ValueError("Local report history is malformed; existing file preserved.") from error
    if not isinstance(records, list):
        raise ValueError("Local report history must be a list.")
    for record in records:
        _validate_report(record)
    return records


def combine_reports(database_records, local_records):
    """Show both sources, matching identical copies once per occurrence.

    Without stable report IDs, equality is only a display reconciliation rule.
    Keep the greater occurrence count of each complete dictionary, preserve
    database order, then append unmatched local records in local order. Do not
    merge differently shaped legacy records, modify sources or upload anything.
    """
    combined = list(database_records)
    unmatched = list(database_records)
    for record in local_records:
        if record in unmatched:
            unmatched.remove(record)
        else:
            combined.append(record)
    return combined


def query(filter_fn):
    # return only the records that match the given check
    return [record for record in load() if filter_fn(record)]
