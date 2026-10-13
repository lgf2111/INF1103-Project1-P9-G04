# data_manager.py
# Saves, loads and queries local JSON reports. OWNER: Pair C.

import json
import os
import tempfile

from misc import logging_setup

logger = logging_setup.get_logger(__name__)

FILE = "reports.json"

REPORT_FIELDS = {
    "channel", "sender", "message", "link", "file_name", "details", "score", "priority",
}


INPUT_FIELDS = {
    "channel",
    "sender",
    "message",
    "has_link",
    "link",
    "has_file",
    "file_name",
    "clicked",
    "downloaded",
    "submitted_category",
}


def _validate_summary(record):
    """Validate the eight-field storage contract without changing the report."""
    if not isinstance(record, dict) or set(record) != REPORT_FIELDS:
        raise ValueError("Reports must contain exactly the eight agreed fields.")
    if not isinstance(record["channel"], str):
        raise ValueError("Invalid report channel.")
    if not isinstance(record["message"], str) or not record["message"].strip():
        raise ValueError("Invalid report message.")
    for key in ("sender", "link", "file_name"):
        if record[key] is not None and not isinstance(record[key], str):
            raise ValueError("Invalid report metadata.")

    # Store extraction as three lists, without normalizing or inventing values.
    details = record["details"]
    if not isinstance(details, dict) or set(details) != {"emails", "phone_numbers", "ip_addresses"}:
        raise ValueError("Invalid stored extraction.")
    for values in details.values():
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError("Invalid stored text lists.")
    if type(record["score"]) is not int or not 0 <= record["score"] <= 100:
        raise ValueError("Invalid stored score.")
    if record["priority"] not in ("LOW", "MEDIUM", "HIGH"):
        raise ValueError("Invalid stored priority.")
    return record


def _validate_result(result):
    """Check the score, priority and guidance shared by versioned reports."""
    if not isinstance(result, dict) or set(result) != {"score", "priority", "reasons", "checklist"}:
        raise ValueError("Invalid stored assessment.")
    if type(result["score"]) is not int or not 0 <= result["score"] <= 100:
        raise ValueError("Invalid stored score.")
    if result["priority"] not in ("LOW", "MEDIUM", "HIGH"):
        raise ValueError("Invalid stored priority.")
    for key in ("reasons", "checklist"):
        values = result[key]
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError("Invalid stored text lists.")


def _validate_v2(record):
    """Validate the exact version-2 storage contract without changing values."""
    if not isinstance(record, dict) or set(record) != {
        "schema_version", "channel", "message", "result",
    }:
        raise ValueError("Version-2 reports must contain exactly the four agreed fields.")
    if type(record["schema_version"]) is not int or record["schema_version"] != 2:
        raise ValueError("New reports must use schema version 2.")
    for key in ("channel", "message"):
        if not isinstance(record[key], str) or not record[key].strip():
            raise ValueError("Invalid report text: " + key)
    # Keep the original message intact; validation never strips or truncates it.
    _validate_result(record["result"])
    return record


def _validate_report(record):
    """Validate stored structure without inventing missing legacy data or scoring."""
    if not isinstance(record, dict):
        raise ValueError("Stored reports must be objects.")
    if "schema_version" not in record:
        if set(record) == REPORT_FIELDS:
            return _validate_summary(record)
        return record  # Older local records retain their original fields.
    if type(record["schema_version"]) is not int or record["schema_version"] not in (1, 2):
        raise ValueError("Unsupported report version.")
    if record["schema_version"] == 2:
        return _validate_v2(record)
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
    if not isinstance(details, dict) or set(details) != {"emails", "phone_numbers", "ip_addresses"}:
        raise ValueError("Invalid stored extraction.")
    _validate_result(record["result"])
    for values in details.values():
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError("Invalid stored text lists.")
    return record


def save(record):
    """Append a version-2 report atomically, preserving existing records.

    ValueError/OSError means the report could not be saved.
    Single-process CLI only: concurrent writers are not supported.
    """
    _validate_v2(record)  # Enforce the new contract before touching history.
    records = load(strict=True)
    records.append(record)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=os.path.dirname(os.path.abspath(FILE)),
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary = stream.name
            json.dump(records, stream, indent=2, ensure_ascii=False, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, FILE)
    finally:
        if temporary is not None and os.path.exists(temporary):
            os.unlink(temporary)


def load(*, strict=False):
    """Read history; log and return [] on failure by default, as required in Phase 1.

    Internal save/history callers use strict=True to distinguish failed reads from
    empty files and preserve corrupt history. Missing files are empty in either mode.
    No terminal output or exception details enter diagnostics.
    """
    try:
        return _read_records()
    except (OSError, ValueError):
        logging_setup.log_failure(
            logger, "Could not read local report history; existing file preserved."
        )
        if strict:
            raise
        return []


def _read_records():
    """Read and validate the file without converting failures into empty history."""
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


def query(filter_fn):
    """Return local reports matching the predicate without changing storage."""
    return [record for record in load() if filter_fn(record)]
