"""Data manager and JSON storage behavior."""

import json
import logging
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from phishreport.ai import AIManager
from phishreport.data import DataManager, JsonReportStorage, json_storage
from phishreport.logging_setup import AppLogging

REAL_EMAILS = Path(__file__).resolve().parents[1] / "fixtures"


# ============================================================================
# Data Manager
# ============================================================================
@pytest.fixture
def data_manager_storage(monkeypatch, tmp_path):
    """Keep all report files in a temporary directory."""
    monkeypatch.chdir(tmp_path)
    return tmp_path / "reports.json"


def data_manager_for(path):
    """Return a DataManager backed by the given JSON file."""
    return DataManager(storage=JsonReportStorage(path))


def data_manager_report():
    """Return a fictional report in the final version-2 storage format."""
    return {
        "schema_version": 2,
        "channel": "email",
        "message": "  Fictional login request\nOriginal second line.  ",
        "result": {
            "score": 90,
            "priority": "HIGH",
            "reasons": ["Password disclosed."],
            "checklist": ["Change the affected password."],
        },
    }


def test_main_data_manager_instance_shares_adapter_reports(cli, data_manager_storage):
    assert isinstance(cli.data_manager, DataManager)
    first = data_manager_report()
    second = {**first, "message": "  Second original message\n"}
    data_manager_for(data_manager_storage).save(first)
    assert cli.app.load_reports() == [first]
    cli.data_manager.save(second)
    assert data_manager_for(data_manager_storage).load(strict=True) == [first, second]


@pytest.mark.parametrize("state", ["missing", "empty", "populated"])
def test_data_manager_startup(cli, data_manager_storage, monkeypatch, state):
    """Load all JSON records before the menu and identify empty history."""
    records = (
        [data_manager_report(), {**data_manager_report(), "channel": "sms"}]
        if state == "populated"
        else []
    )
    if state != "missing":
        data_manager_storage.write_text(json.dumps(records), encoding="utf-8")
    original_load = cli.data_manager.load
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
        return "6"

    monkeypatch.setattr(cli.data_manager, "load", loader)
    monkeypatch.setattr(cli.io_manager, "main_menu", menu)
    notices = Mock()
    monkeypatch.setattr(cli.io_manager, "show_message", notices)
    cli.app.run()
    assert events == ["load", "menu"]
    messages = [call.args[0] for call in notices.call_args_list]
    assert ("No saved reports found." in messages) == (not records)


def test_data_manager_mixed_history(data_manager_storage):
    """Append v2 while preserving six-field, eight-field and version-1 records."""
    legacy = {
        "channel": "email",
        "sender": None,
        "message": "Older report",
        "link": None,
        "file_name": None,
        "details": {"emails": [], "phone_numbers": [], "ip_addresses": []},
    }
    previous = [legacy, {**legacy, "score": 10, "priority": "LOW"}, data_manager_complete_report()]
    data_manager_storage.write_text(json.dumps(previous), encoding="utf-8")
    original = deepcopy(previous)
    record = data_manager_report()
    data_manager_for(data_manager_storage).save(record)
    assert data_manager_for(data_manager_storage).load(strict=True) == original + [record]
    assert json.loads(data_manager_storage.read_text(encoding="utf-8")) == original + [record]


@pytest.mark.parametrize(
    "field,value",
    [
        ("score", True),
        ("score", -1),
        ("score", 101),
        ("score", "45"),
        ("score", 45.5),
        ("priority", 7),
        ("priority", "INVALID"),
        ("reasons", None),
        ("reasons", [1]),
        ("checklist", "text"),
        ("checklist", [" "]),
    ],
)
def test_data_manager_invalid_result(data_manager_storage, field, value):
    """Reject malformed nested results on both saves and reads without overwriting."""
    record = data_manager_report()
    record["result"][field] = value
    data_manager_storage.write_text("[]", encoding="utf-8")
    with pytest.raises(ValueError):
        data_manager_for(data_manager_storage).save(record)
    assert data_manager_storage.read_text() == "[]"

    # The same invalid value must be rejected when it already exists on disk.
    data_manager_storage.write_text(json.dumps([record]), encoding="utf-8")
    before = data_manager_storage.read_bytes()
    assert data_manager_for(data_manager_storage).load() == []
    with pytest.raises(ValueError):
        data_manager_for(data_manager_storage).load(strict=True)
    with pytest.raises(ValueError):
        data_manager_for(data_manager_storage).save(data_manager_report())
    assert data_manager_storage.read_bytes() == before


@pytest.mark.parametrize("field", ["schema_version", "channel", "message", "result"])
def test_data_manager_missing_field(data_manager_storage, field):
    """Require every field in new version-2 records before writing."""
    record = data_manager_report()
    del record[field]
    with pytest.raises(ValueError):
        data_manager_for(data_manager_storage).save(record)
    assert not data_manager_storage.exists()


def test_data_manager_history_error_notice(cli, data_manager_storage, monkeypatch, capsys):
    """Report unreadable history instead of sending an empty list to display."""
    monkeypatch.setattr(cli.data_manager, "load", Mock(side_effect=PermissionError("Read denied")))
    display = Mock()
    monkeypatch.setattr(cli.io_manager, "display_list", display)
    cli.app.view_reports()
    display.assert_not_called()
    assert "Could not load local report history" in capsys.readouterr().out


def test_data_manager_query(data_manager_storage):
    """Require a query to return every matching record without changing storage."""
    records = [
        {"channel": "email", "message": "First match"},
        {"channel": "sms", "message": "Excluded"},
        {"channel": "email", "message": "Second match"},
    ]
    data_manager_storage.write_text(json.dumps(records))
    before = data_manager_storage.read_bytes()

    # Select a noncontiguous subset so returning all records cannot pass.
    found = data_manager_for(data_manager_storage).query(
        lambda record: record["channel"] == "email"
    )
    assert found == [records[0], records[2]]
    assert data_manager_storage.read_bytes() == before


def data_manager_complete_report():
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


def test_data_manager_roundtrip(data_manager_storage):
    """Retain original whitespace and older records when appending a v2 report."""
    legacy = {"message": "Older report", "score": 20, "priority": "LOW"}
    data_manager_storage.write_text(json.dumps([legacy]))
    record = data_manager_report()
    before = deepcopy(record)
    data_manager_for(data_manager_storage).save(record)
    assert data_manager_for(data_manager_storage).load() == [legacy, record]
    assert record == before
    assert "clicked" not in data_manager_for(data_manager_storage).load()[0]


@pytest.mark.parametrize(
    "content", ["{PRIVATE_BROKEN", "{}", "[1]", "[null]", '[{"schema_version": 2}]']
)
def test_data_manager_corrupt_history_is_preserved(data_manager_storage, caplog, capsys, content):
    """Cover default recovery, strict refusal, privacy and unchanged bytes together."""
    data_manager_storage.write_text(content)
    with caplog.at_level(logging.WARNING, logger="data_manager"):
        assert data_manager_for(data_manager_storage).load() == []
    messages = [r.getMessage() for r in caplog.records if r.name == "data_manager"]
    assert len(messages) == 1 and "Could not read local report history" in messages[0]
    assert "PRIVATE" not in messages[0]
    with pytest.raises(ValueError):
        data_manager_for(data_manager_storage).load(strict=True)
    with pytest.raises(ValueError):
        data_manager_for(data_manager_storage).save(data_manager_report())
    assert data_manager_storage.read_text() == content
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    "key,value",
    [
        ("schema_version", 3),
        ("schema_version", True),
        ("schema_version", "2"),
        ("schema_version", 2.0),
        ("channel", None),
        ("channel", []),
        ("channel", " "),
        ("message", None),
        ("message", ["text"]),
        ("message", " "),
        ("result", None),
        ("result", []),
        ("result", {}),
        ("clicked", "no"),
        ("ai", {}),
    ],
)
def test_data_manager_invalid_report(data_manager_storage, key, value):
    """Reject invalid new report fields before any write occurs."""
    data_manager_storage.write_text("[]")
    record = data_manager_report()
    record[key] = value
    with pytest.raises(ValueError):
        data_manager_for(data_manager_storage).save(record)
    assert data_manager_storage.read_text() == "[]"


def test_data_manager_failed_atomic_replace_preserves_old_history(
    data_manager_storage, monkeypatch
):
    data_manager_storage.write_text('[{"message":"Older report"}]')
    before = data_manager_storage.read_bytes()
    monkeypatch.setattr(json_storage.os, "replace", Mock(side_effect=OSError("write failed")))
    with pytest.raises(OSError):
        data_manager_for(data_manager_storage).save(data_manager_report())
    assert data_manager_storage.read_bytes() == before
    assert list(data_manager_storage.parent.glob("*.tmp")) == []


@pytest.mark.parametrize("operation", ["startup", "view", "save"])
@pytest.mark.parametrize(
    "content",
    [
        "{broken",
        '[{"schema_version":2,"channel":"email","message":"Fictional","result":{"priority":7}}]',
    ],
)
def test_data_manager_history_recovery(
    cli, data_manager_storage, monkeypatch, capsys, operation, content
):
    """Keep malformed JSON and invalid v2 records safe across coordinator paths."""
    data_manager_storage.write_text(content)
    monkeypatch.setattr(AppLogging, "setup", lambda: True)
    monkeypatch.setattr(cli.io_manager, "main_menu", lambda: "6")
    if operation == "save":
        record = data_manager_complete_report()
        monkeypatch.setattr(
            cli.io_manager,
            "collect_input",
            lambda: {
                k: v for k, v in record.items() if k not in ("schema_version", "ai", "result")
            },
        )
        client = SimpleNamespace(complete=lambda prompt: json.dumps(record["ai"]))
        monkeypatch.setattr(cli.app, "_ai_manager", AIManager(client=client))
        cli.app.check_message()
    elif operation == "startup":
        cli.app.run()
    else:
        cli.app.view_reports()
    assert data_manager_storage.read_text() == content
    output = capsys.readouterr().out
    assert "Could not" in output
    assert "starting with an empty list" not in output
    assert "No saved reports" not in output


@pytest.mark.parametrize("failure", ["serialization", "flush", "read"])
def test_data_manager_io_failures_preserve_history(data_manager_storage, monkeypatch, failure):
    data_manager_storage.write_text('[{"message":"Existing"}]')
    before = data_manager_storage.read_bytes()
    subject = data_manager_for(data_manager_storage)
    if failure == "serialization":
        monkeypatch.setattr(json_storage.json, "dump", Mock(side_effect=ValueError("Invalid JSON")))
    elif failure == "flush":
        monkeypatch.setattr(json_storage.os, "fsync", Mock(side_effect=OSError("Disk unavailable")))
    else:
        storage = JsonReportStorage(data_manager_storage)
        monkeypatch.setattr(
            storage, "read_records", Mock(side_effect=PermissionError("Read denied"))
        )
        subject = DataManager(storage=storage)
    with pytest.raises((ValueError, OSError)):
        subject.save(data_manager_report())
    assert data_manager_storage.read_bytes() == before
    assert list(data_manager_storage.parent.glob("*.tmp")) == []


def test_data_manager_saved_result_display(cli, data_manager_storage, capsys):
    """Display persisted v2 reasons and guidance without the old input fields."""
    record = data_manager_report()
    data_manager_for(data_manager_storage).save(record)
    cli.io_manager.display_record(data_manager_for(data_manager_storage).load()[0])
    output = capsys.readouterr().out
    assert "Rule-based score: 90" in output
    assert "Password disclosed." in output
    assert "Change the affected password." in output


def test_data_manager_saved_reports_are_visible(cli, data_manager_storage, monkeypatch):
    shared = data_manager_report()
    local_only = deepcopy(shared)
    local_only["message"] = "A separate fictional message"
    data_manager_storage.write_text(json.dumps([shared, local_only]))
    client = SimpleNamespace(complete=Mock())
    monkeypatch.setattr(cli.app, "_ai_manager", AIManager(client=client))
    before = data_manager_storage.read_bytes()
    assert cli.app.load_reports() == [shared, local_only]
    display = Mock()
    monkeypatch.setattr(cli.io_manager, "display_list", display)
    cli.app.view_reports()
    display.assert_called_once_with([shared, local_only])
    assert data_manager_storage.read_bytes() == before
    client.complete.assert_not_called()


def test_data_manager_default_load_handles_read_error_without_exposing_exception(
    monkeypatch, caplog, tmp_path
):
    storage = JsonReportStorage(tmp_path / "reports.json")
    monkeypatch.setattr(storage, "read_records", Mock(side_effect=PermissionError("PRIVATE_PATH")))
    subject = DataManager(storage=storage)
    with caplog.at_level(logging.WARNING, logger="data_manager"):
        assert subject.load() == []
    assert "PRIVATE_PATH" not in caplog.text


@pytest.mark.parametrize(
    "changes",
    [
        {"priority": 7},
        {"message": []},
        {"result": [1]},
        {"channel": []},
        {"clicked": "yes"},
        {"downloaded": 1},
        {"sender": {}},
        {"link": []},
        {"file_name": 3},
        {"submitted_category": []},
        {"score": True},
        {"result": {"priority": 7}},
        {"result": {"score": "90"}},
        {"result": {"reasons": [1]}},
        {"result": {"checklist": None}},
        {"details": []},
        {"details": {"emails": "bad"}},
        {"details": {"phone_numbers": [1]}},
        {"details": {"ip_addresses": None}},
    ],
)
def test_data_manager_legacy_field_corruption_recovers_without_replacing_file(
    cli, data_manager_storage, monkeypatch, capsys, caplog, changes
):
    """Keep malformed historical fields away from display and strict writes."""
    source = Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sample-1.eml"
    legacy = {"message": source.read_text(encoding="utf-8"), **changes}
    data_manager_storage.write_text(json.dumps([legacy]), encoding="utf-8")
    before = data_manager_storage.read_bytes()

    with caplog.at_level(logging.WARNING, logger="data_manager"):
        assert data_manager_for(data_manager_storage).load() == []
    assert "Could not read local report history" in caplog.text
    with pytest.raises(ValueError):
        data_manager_for(data_manager_storage).load(strict=True)
    with pytest.raises(ValueError):
        data_manager_for(data_manager_storage).save(data_manager_report())

    # Startup, explicit history viewing and normal exit must all remain usable.
    monkeypatch.setattr(AppLogging, "setup", lambda: True)
    choices = iter(["4", "6"])
    monkeypatch.setattr(cli.io_manager, "main_menu", lambda: next(choices))
    cli.app.run()
    output = capsys.readouterr().out
    assert "Could not load local report history" in output
    assert "Bye!" in output
    assert data_manager_storage.read_bytes() == before


@pytest.mark.parametrize(
    "legacy",
    [
        {},
        {
            "message": (
                Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "sample-1.eml"
            ).read_text(encoding="utf-8")
        },
        {"channel": None, "message": None, "sender": None, "result": None},
        {"score": 20.5, "priority": "LOW", "details": {"emails": []}},
        {"result": {"score": 45, "priority": "MEDIUM", "reasons": [], "checklist": []}},
    ],
)
def test_data_manager_supported_partial_legacy_fields_remain_readable(
    cli, data_manager_storage, capsys, legacy
):
    """Preserve accepted older shapes without inventing absent findings or actions."""
    data_manager_storage.write_text(json.dumps([legacy]), encoding="utf-8")
    before = data_manager_storage.read_bytes()
    records = data_manager_for(data_manager_storage).load(strict=True)
    cli.io_manager.display_list(records)
    cli.io_manager.display_record(records[0])
    assert records == [legacy]
    assert "Saved reports" in capsys.readouterr().out
    assert data_manager_storage.read_bytes() == before
