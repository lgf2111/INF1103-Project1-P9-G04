"""The combined CLI and Telegram entry point shares one safe report store."""

import asyncio
import threading
import time
from contextlib import nullcontext

import pytest

from phishreport import both as both_module
from phishreport.both import (
    BothApp,
    LockedDataManager,
    build_cli_app,
    build_shared_manager,
)
from phishreport.data import JsonReportStorage, SqliteReportStorage
from phishreport.data.storage import ReportStorage


def make_report(number):
    return {
        "schema_version": 3,
        "assessment_id": f"assessment-{number}",
        "channel": "chat",
        "message": f"message {number}",
        "result": {
            "score": 10,
            "priority": "LOW",
            "reasons": ["Synthetic reason."],
            "checklist": ["Synthetic action."],
        },
    }


class FirstReadBarrierStorage(ReportStorage):
    """Hold both first readers so an unlocked save race is deterministic."""

    def __init__(self, inner, parties=2):
        self._inner = inner
        self._barrier = threading.Barrier(parties)
        self._reads = 0
        self._guard = threading.Lock()

    def read_records(self):
        with self._guard:
            participates = self._reads < 2
            self._reads += 1
        records = self._inner.read_records()
        if participates:
            # Both snapshots are taken before either caller can write them.
            self._barrier.wait(timeout=10)
        return records

    def write_records(self, records):
        self._inner.write_records(records)


def save_many(manager, first, count, start_barrier):
    start_barrier.wait(timeout=10)
    for number in range(first, first + count):
        manager.save(make_report(number))


def run_two_writers(manager):
    start_barrier = threading.Barrier(2)
    errors = []

    def worker(first):
        try:
            save_many(manager, first, 50, start_barrier)
        except BaseException as error:
            errors.append(error)

    threads = [
        threading.Thread(target=worker, args=(first,), name=f"writer-{first}")
        for first in (0, 50)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    return manager.load(strict=True)


def test_two_threads_save_fifty_reports_each_without_losing_any(tmp_path):
    manager = LockedDataManager(SqliteReportStorage(tmp_path / "reports.sqlite3"))

    records = run_two_writers(manager)

    assert len(records) == 100
    assert {record["message"] for record in records} == {
        f"message {number}" for number in range(100)
    }


def test_removing_the_lock_loses_a_concurrent_save(tmp_path):
    storage = FirstReadBarrierStorage(JsonReportStorage(tmp_path / "reports.json"))
    unlocked = LockedDataManager(storage, lock=nullcontext())

    records = run_two_writers(unlocked)

    # Both first readers saw an empty store, so at least one report is gone.
    assert len(records) < 100


def test_bot_failure_is_reported_and_the_cli_still_exits(capsys):
    bot_failed = threading.Event()
    cli_finished = []

    def failing_bot(stop_event):
        bot_failed.set()
        raise RuntimeError("synthetic bot failure")

    def cli_loop():
        assert bot_failed.wait(timeout=10)
        cli_finished.append(True)

    app = BothApp(failing_bot, cli_loop)

    assert app.run() == 0
    assert cli_finished == [True]
    captured = capsys.readouterr()
    assert "Telegram bot stopped unexpectedly" in captured.err
    assert "CLI is still running" in captured.err


@pytest.mark.parametrize("ending", ["quit", "interrupt"])
def test_cli_exit_stops_the_bot_thread(ending):
    stopped = threading.Event()

    def waiting_bot(stop_event):
        assert stop_event.wait(timeout=10)
        stopped.set()

    def cli_loop():
        if ending == "interrupt":
            raise KeyboardInterrupt

    assert BothApp(waiting_bot, cli_loop).run() == 0
    assert stopped.is_set()


class FakeUpdater:
    def __init__(self):
        self.running = False

    async def start_polling(self, **kwargs):
        self.running = True

    async def stop(self):
        self.running = False


class FakeApplication:
    def __init__(self):
        self.updater = FakeUpdater()
        self.running = False
        self.post_init = None
        self.post_stop = None
        self.post_shutdown = None
        self.loop = None
        self.thread_name = None
        self.shut_down = False

    async def initialize(self):
        self.loop = asyncio.get_running_loop()
        self.thread_name = threading.current_thread().name

    async def start(self):
        self.running = True

    async def stop(self):
        self.running = False

    async def shutdown(self):
        self.shut_down = True


def test_bot_worker_uses_its_own_event_loop_and_shuts_down():
    application = FakeApplication()

    def cli_loop():
        for _ in range(500):
            if application.running:
                break
            time.sleep(0.01)
        assert application.running

    def worker(stop_event):
        both_module._bot_worker(application, stop_event)

    assert BothApp(worker, cli_loop).run() == 0
    assert application.thread_name == "phishreport-bot"
    assert application.loop is not None
    assert not application.loop.is_running()
    assert application.shut_down
    assert not application.running
    assert not application.updater.running


def test_building_the_shared_store_needs_no_token_and_defaults_to_sqlite(tmp_path, monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("PHISHREPORT_STORAGE", raising=False)
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", str(tmp_path / "reports.json"))

    manager = build_shared_manager()
    manager.save(make_report(0))

    assert isinstance(manager, LockedDataManager)
    assert manager.load(strict=True) == [make_report(0)]
    assert (tmp_path / "reports.sqlite3").exists()
    assert not (tmp_path / "reports.json").exists()
    assert build_cli_app(manager) is not None


def test_an_explicit_backend_still_overrides_the_sqlite_default(tmp_path, monkeypatch):
    monkeypatch.setenv("PHISHREPORT_STORAGE", "json")
    path = tmp_path / "reports.json"
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", str(path))

    manager = build_shared_manager()
    manager.save(make_report(1))

    assert manager.load(strict=True) == [make_report(1)]
    assert path.exists()
    assert not (tmp_path / "reports.sqlite3").exists()
