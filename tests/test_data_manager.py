"""Check the four storage requirements independently of implementation details."""

import json

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
    replies = iter([
        json.dumps(details),
        json.dumps({
            "response": "Email: demo@example.test, Phone Number: 12345678, "
            "IP Address: 192.0.2.10",
        }),
    ])
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
    assert saved == [{
        "channel": record["channel"],
        "sender": record["sender"],
        "message": record["message"],
        "link": None,
        "file_name": None,
        "details": details,
    }]
    assert len(displayed) == 1
    assert len(api_calls) == 2


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
    assert events == (["database", "menu"] if database_records else
                      ["database", "local", "menu"])
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
    assert data_manager.load() == []
