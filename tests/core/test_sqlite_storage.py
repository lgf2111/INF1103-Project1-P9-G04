"""Connection lifecycle contracts for the incremental SQLite backend."""

import sqlite3
from contextlib import closing

import pytest

from phishreport.data.sqlite_storage import SqliteReportStorage


class ConnectionProbe(SqliteReportStorage):
    """Exercise connection setup while report operations remain unimplemented."""

    def read_records(self):
        raise NotImplementedError

    def write_records(self, records):
        raise NotImplementedError


def test_connections_are_fresh_and_have_independent_transaction_state(tmp_path):
    storage = ConnectionProbe(tmp_path / "reports.sqlite3")
    with closing(storage._connect()) as first, closing(storage._connect()) as second:
        assert first is not second
        first.execute("CREATE TEMP TABLE private_state(value)")
        assert second.execute("SELECT name FROM sqlite_temp_master").fetchall() == []
        first.execute("BEGIN")
        assert first.in_transaction
        assert not second.in_transaction
    with pytest.raises(sqlite3.ProgrammingError):
        first.execute("SELECT 1")


def test_write_connection_configures_wal_timeout_and_explicit_transactions(tmp_path):
    path = tmp_path / "reports.sqlite3"
    with closing(ConnectionProbe(path)._connect()) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (5000,)
        assert connection.isolation_level is None
        assert not connection.in_transaction
        assert connection.execute("SELECT name FROM sqlite_master").fetchall() == []
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("wal",)


def test_readonly_missing_database_does_not_create_file(tmp_path):
    path = tmp_path / "missing.sqlite3"
    with pytest.raises(OSError) as error:
        ConnectionProbe(path)._connect(readonly=True)
    assert isinstance(error.value.__cause__, sqlite3.Error)
    assert not path.exists()


def test_readonly_connection_preserves_database_and_journal_mode(tmp_path):
    path = tmp_path / "reports.sqlite3"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE TABLE existing(value)")
        connection.execute("INSERT INTO existing VALUES (42)")
        connection.commit()
    before = path.read_bytes()
    with closing(ConnectionProbe(path)._connect(readonly=True)) as connection:
        assert connection.execute("SELECT value FROM existing").fetchall() == [(42,)]
        assert connection.execute("PRAGMA journal_mode").fetchone() == ("delete",)
        assert connection.execute("PRAGMA busy_timeout").fetchone() == (5000,)
        assert connection.isolation_level is None
        with pytest.raises(sqlite3.OperationalError):
            connection.execute("CREATE TABLE forbidden(value)")
    assert path.read_bytes() == before
    assert sorted(item.name for item in tmp_path.iterdir()) == ["reports.sqlite3"]


def test_uri_escapes_relative_path_characters(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "reports # % café.sqlite3"
    storage = ConnectionProbe(path.name)
    with closing(storage._connect()) as connection:
        connection.execute("CREATE TABLE marker(value)")
    assert path.exists()
    with closing(storage._connect(readonly=True)) as connection:
        assert connection.execute("SELECT name FROM sqlite_master").fetchall() == [("marker",)]


@pytest.mark.parametrize("readonly", [False, True])
def test_corrupt_file_raises_value_error_with_cause(tmp_path, readonly):
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not a SQLite database" * 100)
    before = path.read_bytes()
    with pytest.raises(ValueError) as error:
        ConnectionProbe(path)._connect(readonly=readonly)
    assert isinstance(error.value.__cause__, sqlite3.DatabaseError)
    assert path.read_bytes() == before


def test_missing_parent_raises_oserror_without_creating_directory(tmp_path):
    path = tmp_path / "missing" / "reports.sqlite3"
    with pytest.raises(OSError) as error:
        ConnectionProbe(path)._connect()
    assert isinstance(error.value.__cause__, sqlite3.OperationalError)
    assert not path.parent.exists()


@pytest.mark.parametrize(
    ("code", "expected"),
    [
        (sqlite3.SQLITE_CORRUPT, ValueError),
        (sqlite3.SQLITE_CORRUPT | (1 << 8), ValueError),
        (sqlite3.SQLITE_NOTADB, ValueError),
        (sqlite3.SQLITE_BUSY, OSError),
        (sqlite3.SQLITE_CANTOPEN, OSError),
    ],
)
def test_configuration_failure_maps_codes_and_closes_connection(
    tmp_path, monkeypatch, code, expected
):
    failure = sqlite3.DatabaseError("injected configuration failure")
    failure.sqlite_errorcode = code
    _assert_failed_configuration_closes(tmp_path, monkeypatch, failure, expected)


def test_configuration_cancellation_closes_connection(tmp_path, monkeypatch):
    _assert_failed_configuration_closes(
        tmp_path, monkeypatch, KeyboardInterrupt(), KeyboardInterrupt
    )


def _assert_failed_configuration_closes(tmp_path, monkeypatch, failure, expected):
    # A real connection lets us observe resource closure after an injected setup failure.
    class FailingConnection(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            raise failure

    connection = sqlite3.connect(":memory:", factory=FailingConnection)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: connection)
    with pytest.raises(expected) as error:
        ConnectionProbe(tmp_path / "reports.sqlite3")._connect()
    if isinstance(failure, sqlite3.Error):
        assert error.value.__cause__ is failure
    else:
        assert error.value is failure
    with pytest.raises(sqlite3.ProgrammingError):
        connection.cursor()


def test_write_connection_rejects_unavailable_wal_and_closes(tmp_path, monkeypatch):
    # In-memory SQLite always returns 'memory' rather than WAL.
    connection = sqlite3.connect(":memory:")
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: connection)
    with pytest.raises(OSError):
        ConnectionProbe(tmp_path / "reports.sqlite3")._connect()
    with pytest.raises(sqlite3.ProgrammingError):
        connection.cursor()


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (sqlite3.DatabaseError("corrupt configuration"), ValueError),
        (sqlite3.OperationalError("locked configuration"), OSError),
        (KeyboardInterrupt(), KeyboardInterrupt),
    ],
)
def test_close_failure_preserves_primary_configuration_error(
    tmp_path, monkeypatch, failure, expected
):
    if isinstance(failure, sqlite3.DatabaseError):
        failure.sqlite_errorcode = (
            sqlite3.SQLITE_BUSY if expected is OSError else sqlite3.SQLITE_CORRUPT
        )
    cleanup_failure = sqlite3.OperationalError("injected close failure")

    class CloseFailingConnection(sqlite3.Connection):
        def execute(self, *args, **kwargs):
            raise failure

        def close(self):
            super().close()
            raise cleanup_failure

    connection = sqlite3.connect(":memory:", factory=CloseFailingConnection)
    monkeypatch.setattr(sqlite3, "connect", lambda *a, **k: connection)
    with pytest.raises(expected) as error:
        ConnectionProbe(tmp_path / "reports.sqlite3")._connect()
    if isinstance(failure, sqlite3.Error):
        assert error.value.__cause__ is failure
    else:
        assert error.value is failure
    assert any(str(cleanup_failure) in note for note in failure.__notes__)
    with pytest.raises(sqlite3.ProgrammingError):
        connection.cursor()

