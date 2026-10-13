"""Check the four storage requirements independently of implementation details."""

import json
import logging
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import data_manager
import main
import pytest


@pytest.fixture
def storage(monkeypatch, tmp_path):
    """Keep all report files in a temporary directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path / "reports.json"


def _report():
    """Return a fictional report in the final version-2 storage format."""
    return {
        "schema_version": 2,
        "channel": "email",
        "message": "  Fictional login request\nOriginal second line.  ",
        "result": {
            "score": 90, "priority": "HIGH", "reasons": ["Password disclosed."],
            "checklist": ["Change the affected password."],
        },
    }


@pytest.mark.parametrize("state", ["missing", "empty", "populated"])
def test_startup(storage, monkeypatch, state):
    """Load all JSON records before the menu and identify empty history."""
    records = [_report(), {**_report(), "channel": "sms"}] if state == "populated" else []
    if state != "missing":
        storage.write_text(json.dumps(records), encoding="utf-8")
    original_load = data_manager.load
    events = []

    def loader(*, strict=False):
        """Track loading while retaining the real file-reading behavior."""
        events.append("load")
        loaded = original_load(strict=strict)
        assert loaded == records
        return loaded

    def menu():
        """Record the first menu and quit without requesting an assessment."""
        events.append("menu")
        return "5"

    monkeypatch.setattr(data_manager, "load", loader)
    monkeypatch.setattr(main.io_manager, "main_menu", menu)
    notices = Mock()
    monkeypatch.setattr(main.io_manager, "show_message", notices)
    main.main()
    assert events == ["load", "menu"]
    messages = [call.args[0] for call in notices.call_args_list]
    assert ("No saved reports found." in messages) == (not records)


def test_mixed_history(storage):
    """Append v2 while preserving six-field, eight-field and version-1 records."""
    legacy = {"channel": "email", "sender": None, "message": "Older report",
              "link": None, "file_name": None,
              "details": {"emails": [], "phone_numbers": [], "ip_addresses": []}}
    previous = [legacy, {**legacy, "score": 10, "priority": "LOW"}, _complete_report()]
    storage.write_text(json.dumps(previous), encoding="utf-8")
    original = deepcopy(previous)
    record = _report()
    data_manager.save(record)
    assert data_manager.load(strict=True) == original + [record]
    assert json.loads(storage.read_text(encoding="utf-8")) == original + [record]


def test_query_priority(storage):
    """Filter nested priorities, preserving record order and original file contents."""
    high = _report()
    low = deepcopy(high)
    low["result"].update(score=10, priority="LOW")
    records = [high, low, high]
    for record in records:
        data_manager.save(record)
    before = storage.read_bytes()
    assert data_manager.load() == records
    assert data_manager.query(lambda record: record["result"]["priority"] == "HIGH") == [high, high]
    assert storage.read_bytes() == before


@pytest.mark.parametrize("field,value", [
    ("score", True), ("score", -1), ("score", 101), ("score", "45"), ("score", 45.5),
    ("priority", 7), ("priority", "INVALID"), ("reasons", None), ("reasons", [1]),
    ("checklist", "text"), ("checklist", [" "]),
])
def test_invalid_result(storage, field, value):
    """Reject malformed nested results on both saves and reads without overwriting."""
    record = _report()
    record["result"][field] = value
    storage.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        data_manager.save(record)
    assert storage.read_text() == "[]"

    # The same invalid value must be rejected when it already exists on disk.
    storage.write_text(json.dumps([record]), encoding="utf-8")
    before = storage.read_bytes()
    assert data_manager.load() == []
    with pytest.raises(ValueError):
        data_manager.load(strict=True)
    with pytest.raises(ValueError):
        data_manager.save(_report())
    assert storage.read_bytes() == before


@pytest.mark.parametrize("field", ["schema_version", "channel", "message", "result"])
def test_missing_field(storage, field):
    """Require every field in new version-2 records before writing."""
    record = _report()
    del record[field]
    with pytest.raises(ValueError):
        data_manager.save(record)
    assert not storage.exists()


def test_history_error_notice(storage, monkeypatch, capsys):
    """Report unreadable history instead of sending an empty list to display."""
    monkeypatch.setattr(data_manager, "load", Mock(side_effect=PermissionError("Read denied")))
    display = Mock()
    monkeypatch.setattr(main.io_manager, "display_list", display)
    main.view_reports()
    display.assert_not_called()
    assert "Could not load local report history" in capsys.readouterr().out


def test_failed_save_displays_result(storage, monkeypatch, capsys):
    """Show the valid assessment even when its JSON write fails."""
    record = _complete_report()
    monkeypatch.setattr(main.io_manager, "collect_input", lambda: {
        key: value for key, value in record.items() if key not in ("schema_version", "ai", "result")
    })
    monkeypatch.setattr(main.ai_manager, "call_api", lambda prompt: json.dumps(record["ai"]))
    monkeypatch.setattr(data_manager.os, "replace", Mock(side_effect=OSError("Write denied")))
    main.check_message()
    output = capsys.readouterr().out
    assert "Could not save the local report" in output
    assert "=== Assessment ===" in output
    assert not storage.exists()


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
    replies = iter(
        [
            json.dumps(
                {
                    "credential_request": False,
                    "suspicious": False,
                    "insufficient_context": False,
                    "details": details,
                }
            )
        ]
    )
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
    assert saved == [{"schema_version": 2, "channel": record["channel"],
                      "message": record["message"], "result": displayed[0]}]
    assert len(displayed) == 1
    assert len(api_calls) == 1


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
        data_manager.load(strict=True)


def _complete_report():
    """Build an older version-1 report for compatibility and input fixtures."""
    return {
        "schema_version": 1,
        "channel": "email",
        "sender": "demo@example.test",
        "message": "Fictional login request",
        "has_link": False,
        "link": None,
        "has_file": False,
        "file_name": None,
        "clicked": False,
        "downloaded": False,
        "submitted_category": "password",
        "ai": {
            "credential_request": True,
            "suspicious": True,
            "insufficient_context": False,
            "details": {"emails": [], "phone_numbers": [], "ip_addresses": []},
        },
        "result": {
            "score": 90,
            "priority": "HIGH",
            "reasons": ["Password disclosed."],
            "checklist": ["Change the affected password."],
        },
    }


def test_roundtrip(storage):
    """Retain original whitespace and older records when appending a v2 report."""
    legacy = {"message": "Older report", "score": 20, "priority": "LOW"}
    storage.write_text(json.dumps([legacy]))
    record = _report()
    before = deepcopy(record)
    data_manager.save(record)
    assert data_manager.load() == [legacy, record]
    assert record == before
    assert "clicked" not in data_manager.load()[0]


@pytest.mark.parametrize("content", ['{broken', '{}', '[1]', '[null]', '[{"schema_version": 2}]'])
def test_corrupt_history_is_preserved(storage, capsys, content):
    storage.write_text(content)
    with pytest.raises(ValueError):
        data_manager.load(strict=True)
    with pytest.raises(ValueError):
        data_manager.save(_report())
    assert storage.read_text() == content
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("key,value", [
    ("schema_version", 3), ("schema_version", True), ("schema_version", "2"),
    ("schema_version", 2.0), ("channel", None), ("channel", []), ("channel", " "),
    ("message", None), ("message", ["text"]), ("message", " "),
    ("result", None), ("result", []), ("result", {}), ("clicked", "no"),
    ("ai", {}), ("result", {"score": True, "priority": "HIGH", "reasons": [], "checklist": []}),
    ("result", {"score": 101, "priority": "HIGH", "reasons": [], "checklist": []}),
])
def test_invalid_report(storage, key, value):
    """Reject invalid new report fields before any write occurs."""
    storage.write_text('[]')
    record = _report()
    record[key] = value
    with pytest.raises(ValueError):
        data_manager.save(record)
    assert storage.read_text() == '[]'


def test_failed_atomic_replace_preserves_old_history(storage, monkeypatch):
    storage.write_text('[{"message":"Older report"}]')
    before = storage.read_bytes()
    monkeypatch.setattr(data_manager.os, "replace", Mock(side_effect=OSError("write failed")))
    with pytest.raises(OSError):
        data_manager.save(_report())
    assert storage.read_bytes() == before
    assert list(storage.parent.glob('*.tmp')) == []


@pytest.mark.parametrize("operation", ["startup", "view", "save"])
@pytest.mark.parametrize("content", [
    '{broken',
    '[{"schema_version":2,"channel":"email","message":"Fictional","result":{"priority":7}}]',
])
def test_history_recovery(storage, monkeypatch, capsys, operation, content):
    """Keep malformed JSON and invalid v2 records safe across coordinator paths."""
    storage.write_text(content)
    monkeypatch.setattr(main.logging_setup, "setup_logging", lambda: True)
    monkeypatch.setattr(main.io_manager, "main_menu", lambda: "5")
    if operation == "save":
        record = _complete_report()
        monkeypatch.setattr(
            main.io_manager,
            "collect_input",
            lambda: {
                k: v for k, v in record.items() if k not in ("schema_version", "ai", "result")
            },
        )
        monkeypatch.setattr(main.ai_manager, "call_api", lambda prompt: json.dumps(record["ai"]))
        main.check_message()
    elif operation == "startup":
        main.main()
    else:
        main.view_reports()
    assert storage.read_text() == content
    output = capsys.readouterr().out
    assert "Could not" in output
    assert "starting with an empty list" not in output
    assert "No saved reports" not in output


@pytest.mark.parametrize("failure", ["serialization", "flush", "read"])
def test_io_failures_preserve_history(storage, monkeypatch, failure):
    storage.write_text('[{"message":"Existing"}]')
    before = storage.read_bytes()
    if failure == "serialization":
        monkeypatch.setattr(data_manager.json, "dump", Mock(side_effect=ValueError("Invalid JSON")))
    elif failure == "flush":
        monkeypatch.setattr(data_manager.os, "fsync", Mock(side_effect=OSError("Disk unavailable")))
    else:
        monkeypatch.setattr(data_manager, "load", Mock(side_effect=PermissionError("Read denied")))
    with pytest.raises((ValueError, OSError)):
        data_manager.save(_report())
    assert storage.read_bytes() == before
    assert list(storage.parent.glob('*.tmp')) == []


def test_saved_result_display(storage, capsys):
    """Display persisted v2 reasons and guidance without the old input fields."""
    record = _report()
    data_manager.save(record)
    main.io_manager.display_record(data_manager.load()[0])
    output = capsys.readouterr().out
    assert "Rule-based score: 90" in output
    assert "Password disclosed." in output
    assert "Change the affected password." in output


def test_saved_reports_are_visible(storage, monkeypatch):
    shared = _report()
    local_only = deepcopy(shared)
    local_only["message"] = "A separate fictional message"
    storage.write_text(json.dumps([shared, local_only]))
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


@pytest.mark.parametrize("content", ["{PRIVATE_BROKEN", "{}", "[null]", '[{"schema_version":2}]'])
def test_default_load_logs_and_returns_empty_without_damaging_history(
    storage, caplog, capsys, content
):
    storage.write_text(content)
    with caplog.at_level(logging.WARNING, logger="data_manager"):
        assert data_manager.load() == []
    assert storage.read_text() == content
    messages = [record.getMessage() for record in caplog.records if record.name == "data_manager"]
    assert len(messages) == 1
    assert "Could not read local report history" in messages[0]
    assert "PRIVATE" not in messages[0] and "Traceback" not in messages[0]
    assert capsys.readouterr().out == ""


def test_default_load_handles_read_error_without_exposing_exception(monkeypatch, caplog):
    monkeypatch.setattr("builtins.open", Mock(side_effect=PermissionError("PRIVATE_PATH")))
    with caplog.at_level(logging.WARNING, logger="data_manager"):
        assert data_manager.load() == []
    assert "PRIVATE_PATH" not in caplog.text


@pytest.mark.parametrize("changes", [
    {"priority": 7}, {"message": []}, {"result": [1]}, {"channel": []},
    {"clicked": "yes"}, {"downloaded": 1}, {"sender": {}},
    {"link": []}, {"file_name": 3}, {"submitted_category": []},
    {"score": True}, {"result": {"priority": 7}},
    {"result": {"score": "90"}}, {"result": {"reasons": [1]}},
    {"result": {"checklist": None}}, {"details": []},
    {"details": {"emails": "bad"}}, {"details": {"phone_numbers": [1]}},
    {"details": {"ip_addresses": None}},
])
def test_legacy_field_corruption_recovers_without_replacing_file(
    storage, monkeypatch, capsys, caplog, changes
):
    """Keep malformed historical fields away from display and strict writes."""
    source = Path(__file__).resolve().parents[1] / "emails" / "sample-1.eml"
    legacy = {"message": source.read_text(encoding="utf-8"), **changes}
    storage.write_text(json.dumps([legacy]), encoding="utf-8")
    before = storage.read_bytes()

    with caplog.at_level(logging.WARNING, logger="data_manager"):
        assert data_manager.load() == []
    assert "Could not read local report history" in caplog.text
    with pytest.raises(ValueError):
        data_manager.load(strict=True)
    with pytest.raises(ValueError):
        data_manager.save(_report())

    # Startup, explicit history viewing and normal exit must all remain usable.
    monkeypatch.setattr(main.logging_setup, "setup_logging", lambda: True)
    choices = iter(["4", "5"])
    monkeypatch.setattr(main.io_manager, "main_menu", lambda: next(choices))
    main.main()
    output = capsys.readouterr().out
    assert "Could not load local report history" in output
    assert "Bye!" in output
    assert storage.read_bytes() == before


@pytest.mark.parametrize("legacy", [
    {}, {"message": (Path(__file__).resolve().parents[1] / "emails" / "sample-1.eml").read_text(encoding="utf-8")},
    {"channel": None, "message": None, "sender": None, "result": None},
    {"score": 20.5, "priority": "LOW", "details": {"emails": []}},
    {"result": {"score": 45, "priority": "MEDIUM", "reasons": [], "checklist": []}},
])
def test_supported_partial_legacy_fields_remain_readable(storage, capsys, legacy):
    """Preserve accepted older shapes without inventing absent findings or actions."""
    storage.write_text(json.dumps([legacy]), encoding="utf-8")
    before = storage.read_bytes()
    records = data_manager.load(strict=True)
    main.io_manager.display_list(records)
    main.io_manager.display_record(records[0])
    assert records == [legacy]
    assert "Saved reports" in capsys.readouterr().out
    assert storage.read_bytes() == before
