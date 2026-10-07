# data_manager.py
# Saves reports locally and in PostgreSQL. OWNER: Pair C.

import json
import os

import psycopg
from psycopg.rows import dict_row
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
    """Insert reports into six PostgreSQL columns without changing the local file.

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
                    "channel TEXT NOT NULL, "
                    "sender TEXT, "
                    "message TEXT NOT NULL, "
                    "link TEXT, "
                    "file_name TEXT, "
                    "details JSONB NOT NULL)"
                )
                # Bind report values separately from SQL, including nested details.
                cursor.executemany(
                    "INSERT INTO reports "
                    "(channel, sender, message, link, file_name, details) "
                    "VALUES (%s, %s, %s, %s, %s, %s)",
                    [
                        (
                            record["channel"],
                            record["sender"],
                            record["message"],
                            record["link"],
                            record["file_name"],
                            Jsonb(record["details"]),
                        )
                        for record in records
                    ],
                )
    except psycopg.Error as error:
        raise RuntimeError("Could not save reports to PostgreSQL.") from error

    return len(records)


def fetch() -> list[dict]:
    """Read the six report fields from PostgreSQL in insertion order.

    Returns:
        Report dictionaries compatible with the existing I/O history display.

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
                # JSONB details are decoded by the driver into Python dictionaries.
                cursor.execute(
                    "SELECT channel, sender, message, link, file_name, details "
                    "FROM reports ORDER BY id"
                )
                return cursor.fetchall()
    except psycopg.Error as error:
        raise RuntimeError("Could not load reports from PostgreSQL.") from error


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
