"""Two real processes appending to the same history must not lose records."""

import json
import multiprocessing
import sqlite3
from contextlib import closing

import pytest

from phishreport.data import DataManager, JsonReportStorage
from phishreport.data.sqlite_storage import SqliteReportStorage
from phishreport.errors import StorageFailure

PER_PROCESS = 25
BACKENDS = {"json": JsonReportStorage, "sqlite": SqliteReportStorage}


def make_report(label, number):
    """Return a fictional v3 report with a unique assessment_id."""
    return {
        "schema_version": 3,
        "assessment_id": f"{label}-{number}",
        "channel": "email",
        "message": f"Fictional message {label}-{number}",
        "result": {"score": 0, "priority": "LOW", "reasons": [], "checklist": []},
    }


def save_many(backend, path, label, ready, go):
    """Process entry point: save PER_PROCESS reports through the real DataManager."""
    manager = DataManager(storage=BACKENDS[backend](path))
    ready.set()
    go.wait(timeout=30)
    for number in range(PER_PROCESS):
        manager.save(make_report(label, number))


def run_two_processes(backend, path):
    context = multiprocessing.get_context("spawn")
    go = context.Event()
    ready = [context.Event(), context.Event()]
    workers = [
        context.Process(target=save_many, args=(backend, str(path), label, event, go))
        for label, event in zip("ab", ready)
    ]
    for worker in workers:
        worker.start()
    for event in ready:
        assert event.wait(timeout=30)
    go.set()
    for worker in workers:
        worker.join(timeout=60)
    assert [worker.exitcode for worker in workers] == [0, 0]


@pytest.mark.parametrize("seeded", [False, True], ids=["new-file", "existing-file"])
@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_two_processes_saving_to_one_history_lose_nothing(tmp_path, backend, seeded):
    path = tmp_path / "reports"
    if seeded:
        BACKENDS[backend](path).write_records([])
    run_two_processes(backend, path)

    records = BACKENDS[backend](path).read_records()
    ids = [record["assessment_id"] for record in records]
    assert len(records) == 2 * PER_PROCESS
    assert len(set(ids)) == 2 * PER_PROCESS
    for label in "ab":
        assert [i for i in ids if i.startswith(label)] == [
            f"{label}-{n}" for n in range(PER_PROCESS)
        ]


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_append_adds_after_existing_records_in_order(tmp_path, backend):
    storage = BACKENDS[backend](tmp_path / "reports")
    storage.append({"n": 1})
    storage.append({"n": 2})
    storage.write_records([{"n": 0}])
    storage.append({"n": 3})
    assert storage.read_records() == [{"n": 0}, {"n": 3}]


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_append_rejects_non_objects_without_touching_history(tmp_path, backend):
    storage = BACKENDS[backend](tmp_path / "reports")
    storage.append({"n": 1})
    with pytest.raises(ValueError):
        storage.append(["not", "an", "object"])
    assert storage.read_records() == [{"n": 1}]


def test_json_append_creates_lock_file_and_leaves_it_usable(tmp_path):
    path = tmp_path / "reports.json"
    storage = JsonReportStorage(path)
    storage.append({"n": 1})
    assert (tmp_path / "reports.json.lock").exists()
    storage.append({"n": 2})
    assert json.loads(path.read_text(encoding="utf-8")) == [{"n": 1}, {"n": 2}]


def test_json_append_releases_lock_when_write_fails(tmp_path, monkeypatch):
    storage = JsonReportStorage(tmp_path / "reports.json")
    storage.append({"n": 1})

    def failing_replace(*_):
        raise OSError("disk full")

    monkeypatch.setattr("phishreport.data.json_storage.os.replace", failing_replace)
    with pytest.raises(OSError):
        storage.append({"n": 2})
    monkeypatch.undo()
    storage.append({"n": 3})  # Would block forever if the lock leaked.
    assert storage.read_records() == [{"n": 1}, {"n": 3}]


def test_json_append_without_fcntl_falls_back_to_unlocked_append(tmp_path, monkeypatch):
    monkeypatch.setattr("phishreport.data.json_storage.fcntl", None)
    storage = JsonReportStorage(tmp_path / "reports.json")
    storage.append({"n": 1})
    assert storage.read_records() == [{"n": 1}]
    assert not (tmp_path / "reports.json.lock").exists()


def test_save_on_corrupt_json_raises_storage_failure_and_preserves_file(tmp_path):
    path = tmp_path / "reports.json"
    path.write_bytes(b"{not json")
    with pytest.raises(StorageFailure):
        DataManager(storage=JsonReportStorage(path)).save(make_report("a", 0))
    assert path.read_bytes() == b"{not json"


def test_sqlite_append_retries_when_database_is_locked(tmp_path, monkeypatch):
    storage = SqliteReportStorage(tmp_path / "reports.sqlite3")
    storage.append({"n": 1})
    real = SqliteReportStorage._append_once
    calls = []

    def flaky(self, payload):
        calls.append(payload)
        if len(calls) < 3:
            error = sqlite3.OperationalError("database is locked")
            error.sqlite_errorcode = sqlite3.SQLITE_BUSY
            raise OSError("busy") from error
        real(self, payload)

    monkeypatch.setattr(SqliteReportStorage, "_append_once", flaky)
    monkeypatch.setattr("phishreport.data.sqlite_storage.time.sleep", lambda _: None)
    storage.append({"n": 2})
    assert len(calls) == 3
    assert storage.read_records() == [{"n": 1}, {"n": 2}]


def test_sqlite_append_gives_up_after_bounded_retries(tmp_path, monkeypatch):
    storage = SqliteReportStorage(tmp_path / "reports.sqlite3")
    calls = []

    def always_busy(self, payload):
        calls.append(payload)
        error = sqlite3.OperationalError("database is locked")
        error.sqlite_errorcode = sqlite3.SQLITE_BUSY
        raise OSError("busy") from error

    monkeypatch.setattr(SqliteReportStorage, "_append_once", always_busy)
    monkeypatch.setattr("phishreport.data.sqlite_storage.time.sleep", lambda _: None)
    with pytest.raises(OSError):
        storage.append({"n": 1})
    assert len(calls) == 4


def test_sqlite_append_rolls_back_on_incompatible_schema(tmp_path):
    path = tmp_path / "reports.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE records(position INTEGER PRIMARY KEY, other TEXT)")
        connection.commit()
    with pytest.raises(ValueError):
        SqliteReportStorage(path).append({"n": 1})
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT COUNT(*) FROM records").fetchone() == (0,)
