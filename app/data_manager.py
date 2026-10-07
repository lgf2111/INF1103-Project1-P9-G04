# data_manager.py
# Saves reports locally and in PostgreSQL. OWNER: Pair C.

import json
import os

import psycopg
from psycopg.types.json import Jsonb

FILE = "reports.json"


def save(record):
    """Append a local report, then upload it to PostgreSQL.

    Raises:
        OSError: If writing the local file fails.
        RuntimeError: If database saving fails; the local copy remains saved.
        ValueError: If the report does not match the six-field database contract.
    """
    # Keep the local copy even when the subsequent database request fails.
    records = load()
    records.append(record)
    with open(FILE, "w") as f:
        json.dump(records, f, indent=2)
    upload([record])


def upload(records: list[dict]) -> int:
    """Insert six-field reports into PostgreSQL without changing the local file.

    Creates the reports table if absent and inserts the batch in one transaction.
    Returns the number inserted. Repeating an upload inserts another copy.

    Raises:
        ValueError: If reports do not contain the six agreed fields.
        RuntimeError: If configuration is missing or the database operation fails.
    """
    fields = {"channel", "sender", "message", "link", "file_name", "details"}
    if not isinstance(records, list):
        raise ValueError("Reports must be a list.")
    for record in records:
        if not isinstance(record, dict) or set(record) != fields:
            raise ValueError("Reports must contain exactly the six agreed fields.")

    # Read configuration after main has loaded .env; never include it in errors.
    database_url = os.environ.get("DATABASE_URL", "").strip().strip("\"'")
    if not database_url:
        raise RuntimeError("Set DATABASE_URL before saving to PostgreSQL.")

    try:
        # The connection context commits on success and rolls back on failure.
        with psycopg.connect(database_url, connect_timeout=10) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "CREATE TABLE IF NOT EXISTS reports ("
                    "id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY, "
                    "payload JSONB NOT NULL)"
                )
                # Bind report values separately from SQL, including nested details.
                cursor.executemany(
                    "INSERT INTO reports (payload) VALUES (%s)",
                    [(Jsonb(record),) for record in records],
                )
    except psycopg.Error as error:
        raise RuntimeError("Could not save reports to PostgreSQL.") from error

    return len(records)


def load():
    # return all records, or [] if the file is missing or broken
    if not os.path.exists(FILE):
        return []
    try:
        with open(FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        print("Warning: could not read", FILE, "- starting with an empty list.")
        return []


def query(filter_fn):
    # return only the records that match the given check
    return [record for record in load() if filter_fn(record)]
