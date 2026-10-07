"""Check the four storage requirements independently of implementation details."""

import json
from copy import deepcopy
from unittest.mock import MagicMock, Mock

import data_manager
import main
import pytest


@pytest.fixture
def storage(monkeypatch, tmp_path):
    """Isolate report files and prevent database requests during offline checks."""
    # Keep test data away from real reports and replace the database boundary.
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/test")
    def upload(records):
        """Replace database writes with a deterministic batch count."""
        return len(records)

    monkeypatch.setattr(data_manager, "upload", upload)
    return tmp_path / "reports.json"


def test_save(storage, monkeypatch):
    """Require main to save a processed report as valid JSON with the agreed fields."""
    details = {
        "emails": ["demo@example.test"],
        "phone_numbers": ["12345678"],
        "ip_addresses": ["192.0.2.10"],
    }
    record = {
        "channel": "email",
        "sender": "demo@example.test",
        "message": "Contact demo@example.test or 12345678. Origin: 192.0.2.10",
        "has_link": False,
        "link": None,
        "has_file": False,
        "file_name": None,
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
    }
    replies = iter([json.dumps({
        "credential_request": False, "suspicious": False, "insufficient_context": False,
        "details": details,
    })])
    api_calls = []
    displayed = []

    def collect():
        """Return the fictional input record."""
        return record

    def call(prompt):
        """Record each prompt and return its next synthetic AI response."""
        api_calls.append(prompt)
        return next(replies)

    def display(result):
        """Record the assessment supplied to the I/O layer."""
        displayed.append(result)

    monkeypatch.setattr(main.io_manager, "collect_input", collect)
    monkeypatch.setattr(main.ai_manager, "call_api", call)
    monkeypatch.setattr(main.io_manager, "display_result", display)

    # Run the actual coordinator, then read its persisted output independently.
    main.check_message()
    saved = json.loads(storage.read_text())
    assert saved == [{**record, "schema_version": 1, "ai": {
        "credential_request": False, "suspicious": False, "insufficient_context": False,
        "details": details,
    }, "result": displayed[0]}]
    assert len(displayed) == 1
    assert len(api_calls) == 1


def test_upload_and_fetch_score_and_priority(monkeypatch):
    """Persist scores and priorities as PostgreSQL columns and return them."""
    cursor = MagicMock()
    cursor_context = MagicMock()
    cursor_context.__enter__.return_value = cursor
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value = cursor_context
    fetched = [{
        "channel": "email",
        "sender": "demo@example.test",
        "message": "A fictional report",
        "link": None,
        "file_name": None,
        "details": {"emails": []},
        "score": 72,
        "priority": "HIGH",
    }]
    cursor.fetchall.return_value = fetched

    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/test")
    monkeypatch.setattr(
        data_manager.psycopg, "connect", lambda *args, **kwargs: connection
    )

    record = {
        "channel": "email",
        "sender": "demo@example.test",
        "message": "A fictional report",
        "link": None,
        "file_name": None,
        "details": {"emails": []},
        "score": 72,
        "priority": "HIGH",
    }
    assert data_manager.upload([record]) == 1
    insert_sql, values = cursor.executemany.call_args.args
    assert "(channel, sender, message, link, file_name, details, score, priority)" in insert_sql
    assert values[0][-2:] == (72, "HIGH")

    assert data_manager.fetch() == fetched
    select_sql = cursor.execute.call_args.args[0]
    assert "score, priority" in select_sql


@pytest.mark.parametrize(
    "database_records, local_records, failed",
    [
        ([{"message": "Database one"}, {"message": "Database two"}], [], False),
        ([], [{"message": "Local one"}, {"message": "Local two"}], False),
        ([], [{"message": "Local one"}, {"message": "Local two"}], True),
        ([], [], False),
        ([], [], True),
    ],
    ids=["database", "empty-database", "database-failure", "both-empty", "failure-empty"],
)
def test_startup(storage, monkeypatch, database_records, local_records, failed):
    """Require startup reads, local fallback, and empty-history notifications."""
    storage.write_text(json.dumps(local_records))
    events = []
    local_load = data_manager.load
    messages = []

    def loader():
        """Record local fallback and read the temporary JSON file."""
        events.append("local")
        return local_load()

    def fetch():
        """Record the database attempt and simulate its configured outcome."""
        events.append("database")
        if failed:
            raise RuntimeError("Connection unavailable")
        return database_records

    def menu():
        """Record the first menu and immediately quit."""
        events.append("menu")
        return "3"

    def notice(message):
        """Capture notices without printing during the test."""
        messages.append(message)

    monkeypatch.setattr(data_manager, "fetch", fetch)
    monkeypatch.setattr(data_manager, "load", loader)
    monkeypatch.setattr(main.io_manager, "main_menu", menu)
    monkeypatch.setattr(main.io_manager, "show_message", notice)

    # Quitting immediately distinguishes startup loading from history viewing.
    main.main()
    assert events == ["database", "local", "menu"]
    assert ("No saved reports found." in messages) == (not database_records and not local_records)
    assert any("PostgreSQL unavailable" in message for message in messages) == failed


def test_query(storage):
    """Require a query to return every matching record without changing storage."""
    records = [
        {"channel": "email", "message": "First match"},
        {"channel": "sms", "message": "Excluded"},
        {"channel": "email", "message": "Second match"},
    ]
    storage.write_text(json.dumps(records))
    before = storage.read_bytes()

    # Select a noncontiguous subset so returning all records cannot pass.
    found = data_manager.query(lambda record: record["channel"] == "email")
    assert found == [records[0], records[2]]
    assert storage.read_bytes() == before


def test_file_errors(storage):
    """Require missing and malformed JSON files to load without crashing."""
    # Start with no file, then repeat with invalid JSON at the same location.
    assert not storage.exists()
    assert data_manager.load() == []
    storage.write_text("{invalid JSON")
    with pytest.raises(ValueError):
        data_manager.load()


def _complete_report():
    return {
        "schema_version": 1, "channel": "email", "sender": "demo@example.test",
        "message": "Fictional login request", "has_link": False, "link": None,
        "has_file": False, "file_name": None, "clicked": False, "downloaded": False,
        "submitted_category": "password",
        "ai": {"credential_request": True, "suspicious": True,
               "insufficient_context": False,
               "details": {"emails": [], "phone_numbers": [], "ip_addresses": []}},
        "result": {"score": 90, "priority": "HIGH", "reasons": ["Password disclosed."],
                   "checklist": ["Change the affected password."]},
    }


def test_complete_local_roundtrip_preserves_legacy_and_input(storage, monkeypatch):
    legacy = {"message": "Older report", "score": 20, "priority": "LOW"}
    storage.write_text(json.dumps([legacy]))
    record = _complete_report()
    before = deepcopy(record)
    upload = Mock(return_value=1)
    monkeypatch.setattr(data_manager, "upload", upload)
    data_manager.save(record)
    assert data_manager.load() == [legacy, record]
    assert record == before
    assert "clicked" not in data_manager.load()[0]
    upload.assert_called_once_with([record])


@pytest.mark.parametrize("content", ['{broken', '{}', '[1]', '[null]', '[{"schema_version": 2}]'])
def test_corrupt_history_is_preserved_and_never_uploaded(storage, monkeypatch, capsys, content):
    storage.write_text(content)
    upload = Mock()
    monkeypatch.setattr(data_manager, "upload", upload)
    with pytest.raises(ValueError):
        data_manager.load()
    with pytest.raises(ValueError):
        data_manager.save(_complete_report())
    assert storage.read_text() == content
    upload.assert_not_called()
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("key,value", [
    ("schema_version", 2), ("schema_version", True), ("clicked", "no"),
    ("ai", {}), ("result", {"score": True, "priority": "HIGH", "reasons": [], "checklist": []}),
    ("result", {"score": 101, "priority": "HIGH", "reasons": [], "checklist": []}),
])
def test_invalid_complete_report_rejected_before_write(storage, monkeypatch, key, value):
    storage.write_text('[]')
    record = _complete_report()
    record[key] = value
    upload = Mock()
    monkeypatch.setattr(data_manager, "upload", upload)
    with pytest.raises(ValueError):
        data_manager.save(record)
    assert storage.read_text() == '[]'
    upload.assert_not_called()


def test_failed_atomic_replace_preserves_old_history(storage, monkeypatch):
    storage.write_text('[{"message":"Older report"}]')
    before = storage.read_bytes()
    upload = Mock()
    monkeypatch.setattr(data_manager, "upload", upload)
    monkeypatch.setattr(data_manager.os, "replace", Mock(side_effect=OSError("write failed")))
    with pytest.raises(OSError):
        data_manager.save(_complete_report())
    assert storage.read_bytes() == before
    assert list(storage.parent.glob('*.tmp')) == []
    upload.assert_not_called()


def test_database_failure_keeps_complete_local_record(storage, monkeypatch):
    monkeypatch.setattr(data_manager, "upload", Mock(side_effect=RuntimeError("Unavailable")))
    with pytest.raises(RuntimeError):
        data_manager.save(_complete_report())
    assert data_manager.load() == [_complete_report()]


def test_complete_postgresql_roundtrip_without_schema_migration(monkeypatch):
    cursor = MagicMock()
    connection = MagicMock()
    connection.__enter__.return_value = connection
    connection.cursor.return_value.__enter__.return_value = cursor
    monkeypatch.setenv("DATABASE_URL", "postgresql://example.invalid/test")
    monkeypatch.setattr(data_manager.psycopg, "connect", Mock(return_value=connection))
    record = _complete_report()
    assert data_manager.upload([record]) == 1
    sql, rows = cursor.executemany.call_args.args
    assert rows[0][-2:] == (90, "HIGH")
    payload = json.loads(rows[0][5])
    assert payload == {"schema_version": 1, "record": record}
    legacy = {"channel": "sms", "sender": None, "message": "Older report",
              "link": None, "file_name": None, "details": {"emails": []},
              "score": None, "priority": None}
    row = {key: record[key] for key in ("channel", "sender", "message", "link", "file_name")}
    row.update(details=payload, score=90, priority="HIGH")
    cursor.fetchall.return_value = [legacy, row]
    assert data_manager.fetch() == [legacy, record]
    row["score"] = 10
    with pytest.raises(ValueError):
        data_manager.fetch()


@pytest.mark.parametrize("operation", ["startup", "view", "save"])
def test_coordinator_handles_broken_local_history(storage, monkeypatch, capsys, operation):
    storage.write_text('{broken')
    monkeypatch.setattr(data_manager, "fetch", Mock(side_effect=RuntimeError("Unavailable")))
    monkeypatch.setattr(main, "configure_logging", lambda: None)
    monkeypatch.setattr(main.io_manager, "main_menu", lambda: "3")
    if operation == "save":
        record = _complete_report()
        monkeypatch.setattr(main.io_manager, "collect_input", lambda: {
            k: v for k, v in record.items() if k not in ("schema_version", "ai", "result")})
        monkeypatch.setattr(main.ai_manager, "call_api", lambda prompt: json.dumps(record["ai"]))
        main.check_message()
    elif operation == "startup":
        main.main()
    else:
        main.view_reports()
    assert storage.read_text() == '{broken'
    output = capsys.readouterr().out
    assert "Could not" in output
    assert "starting with an empty list" not in output
    assert "No saved reports" not in output


@pytest.mark.parametrize("failure", ["serialization", "flush", "read"])
def test_io_failures_do_not_upload_or_damage_history(storage, monkeypatch, failure):
    storage.write_text('[{"message":"Existing"}]')
    before = storage.read_bytes()
    upload = Mock()
    monkeypatch.setattr(data_manager, "upload", upload)
    if failure == "serialization":
        monkeypatch.setattr(data_manager.json, "dump", Mock(side_effect=ValueError("Invalid JSON")))
    elif failure == "flush":
        monkeypatch.setattr(data_manager.os, "fsync", Mock(side_effect=OSError("Disk unavailable")))
    else:
        monkeypatch.setattr(data_manager, "load", Mock(side_effect=PermissionError("Read denied")))
    with pytest.raises((ValueError, OSError)):
        data_manager.save(_complete_report())
    assert storage.read_bytes() == before
    assert list(storage.parent.glob('*.tmp')) == []
    upload.assert_not_called()


@pytest.mark.parametrize("database_failure", [False, True])
def test_coordinator_distinguishes_local_and_database_failure(
    storage, monkeypatch, capsys, database_failure
):
    record = _complete_report()
    monkeypatch.setattr(main.io_manager, "collect_input", lambda: {
        k: v for k, v in record.items() if k not in ("schema_version", "ai", "result")})
    monkeypatch.setattr(main.ai_manager, "call_api", lambda prompt: json.dumps(record["ai"]))
    upload = Mock(side_effect=RuntimeError("Unavailable"))
    monkeypatch.setattr(data_manager, "upload", upload)
    if not database_failure:
        monkeypatch.setattr(data_manager.os, "replace", Mock(side_effect=OSError("Write denied")))
    main.check_message()
    output = capsys.readouterr().out
    assert "=== Assessment ===" in output  # Assessment succeeded even if storage failed.
    if database_failure:
        assert "Report saved locally, but database saving failed" in output
        assert data_manager.load()[0]["ai"] == record["ai"]
    else:
        assert "Could not save the local report" in output
        assert "Report saved locally" not in output
        assert not storage.exists()
        upload.assert_not_called()


def test_saved_complete_report_displays_actions_and_result(storage, capsys):
    record = _complete_report()
    data_manager.save(record)
    main.io_manager.display_record(data_manager.load()[0])
    output = capsys.readouterr().out
    assert "Information submitted: Password" in output
    assert "Rule-based score: 90" in output
    assert "Password disclosed." in output
    assert "Change the affected password." in output


@pytest.mark.parametrize("database,local,expected", [
    ([{"message": "Shared"}], [{"message": "Shared"}, {"message": "Local only"}],
     [{"message": "Shared"}, {"message": "Local only"}]),
    ([{"message": "Shared"}], [{"message": "Shared"}, {"message": "Shared"}],
     [{"message": "Shared"}, {"message": "Shared"}]),
    ([{"message": "Shared"}, {"message": "Shared"}], [{"message": "Shared"}],
     [{"message": "Shared"}, {"message": "Shared"}]),
    ([], [{"message": "Local only"}], [{"message": "Local only"}]),
    ([{"message": "Database only"}], [], [{"message": "Database only"}]),
    ([{"message": "Old", "score": 10}], [{"message": "Old", "result": {"score": 10}}],
     [{"message": "Old", "score": 10}, {"message": "Old", "result": {"score": 10}}]),
])
def test_history_combines_sources_without_losing_repeated_assessments(database, local, expected):
    before = deepcopy((database, local))
    assert data_manager.combine_reports(database, local) == expected
    assert (database, local) == before


def test_saved_local_report_remains_visible_with_nonempty_database(storage, monkeypatch):
    shared = _complete_report()
    local_only = deepcopy(shared)
    local_only["message"] = "A separate fictional message"
    storage.write_text(json.dumps([shared, local_only]))
    monkeypatch.setattr(data_manager, "fetch", Mock(return_value=[shared]))
    upload = Mock()
    monkeypatch.setattr(data_manager, "upload", upload)
    api = Mock()
    monkeypatch.setattr(main.ai_manager, "call_api", api)
    before = storage.read_bytes()
    assert main.load_reports() == [shared, local_only]
    display = Mock()
    monkeypatch.setattr(main.io_manager, "display_list", display)
    main.view_reports()
    display.assert_called_once_with([shared, local_only])
    assert storage.read_bytes() == before
    api.assert_not_called()
    upload.assert_not_called()


def test_database_history_remains_available_when_local_history_is_corrupt(
    storage, monkeypatch, capsys
):
    storage.write_text('{broken')
    records = [_complete_report()]
    monkeypatch.setattr(data_manager, "fetch", Mock(return_value=records))
    assert main.load_reports() == records
    assert "Could not load local report history" in capsys.readouterr().out
    assert storage.read_text() == '{broken'


@pytest.mark.parametrize("database_available", [False, True])
def test_unreadable_local_history_is_reported_even_with_database(
    storage, monkeypatch, capsys, database_available
):
    records = [_complete_report()] if database_available else []
    monkeypatch.setattr(data_manager, "fetch", Mock(return_value=records))
    monkeypatch.setattr(data_manager, "load", Mock(side_effect=PermissionError("Read denied")))
    assert main.load_reports() == (records if database_available else None)
    assert "Could not load local report history" in capsys.readouterr().out
