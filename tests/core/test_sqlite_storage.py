"""Connection lifecycle contracts for the incremental SQLite backend."""

import os
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from phishreport.data.sqlite_storage import SqliteReportStorage


class ReadProbe(SqliteReportStorage):
    """Leave only the unassigned write operation stubbed."""

    def write_records(self, records):
        raise NotImplementedError


def _seed_records(path, rows=(), schema=None):
    with closing(sqlite3.connect(path)) as connection:
        connection.execute(
            schema or "CREATE TABLE records(position INTEGER PRIMARY KEY, payload TEXT)"
        )
        if rows:
            connection.executemany("INSERT INTO records VALUES (?, ?)", rows)
        connection.commit()


@pytest.mark.parametrize("missing_parent", [False, True])
def test_read_absent_returns_empty_without_creating_paths(tmp_path, missing_parent):
    path = (
        tmp_path / "missing" / "reports.sqlite3" if missing_parent else tmp_path / "reports.sqlite3"
    )
    assert ReadProbe(path).read_records() == []
    assert list(tmp_path.iterdir()) == []


def test_read_stat_permission_failure_is_not_hidden(tmp_path, monkeypatch):
    failure = PermissionError("denied")

    def denied_stat(self, *args, **kwargs):
        raise failure

    monkeypatch.setattr(Path, "stat", denied_stat)
    with pytest.raises(PermissionError) as error:
        ReadProbe(tmp_path / "reports.sqlite3").read_records()
    assert error.value is failure


def test_read_orders_and_returns_fresh_nested_historical_fields(tmp_path):
    path = tmp_path / "reports.sqlite3"
    _seed_records(path, [(9, '{"old":{"items":[1,{"x":true}]}}'), (-2, '{"unknown":"café"}')])
    before = path.read_bytes()
    storage = ReadProbe(path)
    records = storage.read_records()
    assert records == [{"unknown": "café"}, {"old": {"items": [1, {"x": True}]}}]
    records[1]["old"]["items"][1]["x"] = False
    assert ReadProbe(path).read_records() == [
        {"unknown": "café"},
        {"old": {"items": [1, {"x": True}]}},
    ]
    assert path.read_bytes() == before
    assert sorted(item.name for item in tmp_path.iterdir()) == ["reports.sqlite3"]


@pytest.mark.parametrize(
    "schema",
    [
        "CREATE TABLE other(value)",
        "CREATE VIEW records AS SELECT 1 AS position, '{}' AS payload",
        "CREATE TABLE records(position INT PRIMARY KEY, payload TEXT)",
        "CREATE TABLE records(position INTEGER, payload TEXT)",
        "CREATE TABLE records(position INTEGER PRIMARY KEY, payload BLOB)",
        "CREATE TABLE records(position INTEGER PRIMARY KEY, payload TEXT, extra TEXT)",
        "CREATE TABLE records(position INTEGER, payload TEXT, PRIMARY KEY(position,payload))",
        "CREATE TABLE records(position INTEGER PRIMARY KEY, payload TEXT, "
        "extra TEXT GENERATED ALWAYS AS (payload) VIRTUAL)",
    ],
)
def test_read_rejects_incompatible_schema_and_preserves_bytes(tmp_path, schema):
    path = tmp_path / "reports.sqlite3"
    _seed_records(path, schema=schema)
    before = path.read_bytes()
    with pytest.raises(ValueError):
        ReadProbe(path).read_records()
    assert path.read_bytes() == before


def test_read_rejects_desc_primary_key_that_allows_noninteger_positions(tmp_path):
    path = tmp_path / "reports.sqlite3"
    _seed_records(
        path,
        [(None, "{}"), ("text position", "{}")],
        "CREATE TABLE records(position INTEGER PRIMARY KEY DESC, payload TEXT)",
    )
    before = path.read_bytes()
    with pytest.raises(ValueError):
        ReadProbe(path).read_records()
    assert path.read_bytes() == before


def test_read_accepts_secondary_indexes_and_triggers(tmp_path):
    path = tmp_path / "reports.sqlite3"
    _seed_records(path, [(1, '{"legacy":true}')])
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE INDEX payload_index ON records(payload)")
        connection.execute(
            "CREATE TRIGGER reject_insert BEFORE INSERT ON records "
            "BEGIN SELECT RAISE(ABORT, 'reject'); END"
        )
        connection.commit()
    assert ReadProbe(path).read_records() == [{"legacy": True}]


@pytest.mark.parametrize(
    "payload",
    [
        None,
        b"{}",
        "[]",
        "null",
        "42",
        '"object"',
        "{} {}",
        '{"a":1,"a":2}',
        '{"a":{"x":1,"x":2}}',
        '{"x":NaN}',
        '{"x":Infinity}',
        "{",
    ],
)
def test_read_rejects_malformed_payload_without_changing_bytes(tmp_path, payload):
    path = tmp_path / "reports.sqlite3"
    _seed_records(path, [(1, payload)])
    before = path.read_bytes()
    with pytest.raises(ValueError):
        ReadProbe(path).read_records()
    assert path.read_bytes() == before


def test_read_rejects_invalid_utf8_text(tmp_path):
    path = tmp_path / "reports.sqlite3"
    _seed_records(path)
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("INSERT INTO records VALUES (1, CAST(x'ff' AS TEXT))")
        connection.commit()
    with pytest.raises(ValueError):
        ReadProbe(path).read_records()


@pytest.mark.parametrize("contents", [b"", b"not a database" * 100])
def test_read_rejects_existing_invalid_database(tmp_path, contents):
    path = tmp_path / "reports.sqlite3"
    path.write_bytes(contents)
    with pytest.raises(ValueError):
        ReadProbe(path).read_records()
    assert path.read_bytes() == contents


def test_read_honors_committed_wal_and_one_snapshot(tmp_path, monkeypatch):
    path = tmp_path / "reports.sqlite3"
    with closing(sqlite3.connect(path, isolation_level=None)) as writer:
        writer.execute("PRAGMA journal_mode=WAL")
        writer.execute("CREATE TABLE records(position INTEGER PRIMARY KEY, payload TEXT)")
        writer.execute("INSERT INTO records VALUES (1, '{\"version\":1}')")

        class ConcurrentConnection(sqlite3.Connection):
            def execute(self, sql, *args, **kwargs):
                cursor = super().execute(sql, *args, **kwargs)
                if "sqlite_master" in sql or "sqlite_schema" in sql:
                    writer.execute("UPDATE records SET payload = '{\"version\":2}'")
                return cursor

        reader = sqlite3.connect(path, isolation_level=None, factory=ConcurrentConnection)
        monkeypatch.setattr(ReadProbe, "_connect", lambda self, *, readonly: reader)
        assert ReadProbe(path).read_records() == [{"version": 1}]
        with pytest.raises(sqlite3.ProgrammingError):
            reader.cursor()
        monkeypatch.undo()
        assert ReadProbe(path).read_records() == [{"version": 2}]


@pytest.mark.parametrize(
    "code,expected",
    [
        (sqlite3.SQLITE_BUSY, OSError),
        (sqlite3.SQLITE_IOERR, OSError),
        (sqlite3.SQLITE_CORRUPT, ValueError),
    ],
)
def test_read_failure_maps_cause_and_closes(tmp_path, monkeypatch, code, expected):
    path = tmp_path / "reports.sqlite3"
    _seed_records(path)
    failure = sqlite3.OperationalError("injected read failure")
    failure.sqlite_errorcode = code

    class FailingReadConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("SELECT payload"):
                raise failure
            return super().execute(sql, *args, **kwargs)

        def close(self):
            super().close()
            raise sqlite3.OperationalError("injected close failure")

    reader = sqlite3.connect(path, isolation_level=None, factory=FailingReadConnection)
    monkeypatch.setattr(ReadProbe, "_connect", lambda self, *, readonly: reader)
    with pytest.raises(expected) as error:
        ReadProbe(path).read_records()
    assert error.value.__cause__ is failure
    assert any("close failure" in note for note in error.value.__notes__)
    with pytest.raises(sqlite3.ProgrammingError):
        reader.cursor()


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


def test_write_replaces_in_order_and_preserves_nested_unicode_values(tmp_path):
    path = tmp_path / "reports.sqlite3"
    storage = SqliteReportStorage(path)
    records = [{"nested": [None, True, {"text": "café 雪 ' ?"}]}, {"old": 2}]
    assert storage.write_records(records) is None
    records[0]["nested"].append("changed")
    assert storage.read_records() == [
        {"nested": [None, True, {"text": "café 雪 ' ?"}]}, {"old": 2}
    ]
    storage.write_records([{"replacement": 3}])
    assert storage.read_records() == [{"replacement": 3}]
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute("SELECT position FROM records").fetchall() == [(0,)]
    storage.write_records([])
    assert storage.read_records() == []


@pytest.mark.parametrize("existing", [False, True])
@pytest.mark.parametrize(
    "records,error_type",
    [(None, ValueError), ({}, ValueError), ([1], ValueError),
     ([{"bad": object()}], TypeError), ([{"bad": float("nan")}], ValueError)],
)
def test_write_invalid_input_preserves_files_before_connection(
    tmp_path, existing, records, error_type
):
    path = tmp_path / "reports.sqlite3"
    if existing:
        _seed_records(path, [(5, '{"old":true}')])
    before = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
    with pytest.raises(error_type):
        SqliteReportStorage(path).write_records(records)
    assert {item.name: item.read_bytes() for item in tmp_path.iterdir()} == before


@pytest.mark.parametrize(
    "schema",
    ["CREATE TABLE other(value)",
     "CREATE VIEW records AS SELECT 1 AS position, '{}' AS payload",
     "CREATE TABLE records(position INT PRIMARY KEY, payload TEXT)",
     "CREATE TABLE records(position INTEGER PRIMARY KEY DESC, payload TEXT)",
     "CREATE TABLE records(position INTEGER PRIMARY KEY, payload TEXT, extra TEXT)",
     "CREATE TABLE records(position INTEGER PRIMARY KEY, payload BLOB)"],
)
def test_write_rejects_existing_incompatible_schema(tmp_path, schema):
    path = tmp_path / "reports.sqlite3"
    _seed_records(path, schema=schema)
    with pytest.raises(ValueError):
        SqliteReportStorage(path).write_records([{"new": True}])
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT sql FROM sqlite_master WHERE name IN ('records', 'other')"
        ).fetchone() == (schema,)


def test_write_trigger_abort_rolls_back_all_rows_and_allows_later_write(tmp_path):
    path = tmp_path / "reports.sqlite3"
    _seed_records(path, [(7, '{"old":true}')])
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("CREATE INDEX payload_index ON records(payload)")
        connection.execute(
            "CREATE TRIGGER reject_later BEFORE INSERT ON records WHEN NEW.position = 1 "
            "BEGIN SELECT RAISE(ABORT, 'reject later insert'); END"
        )
        connection.commit()
    storage = SqliteReportStorage(path)
    with pytest.raises(OSError) as error:
        storage.write_records([{"first": True}, {"second": True}])
    assert isinstance(error.value.__cause__, sqlite3.IntegrityError)
    assert storage.read_records() == [{"old": True}]
    storage.write_records([{"later": True}])
    assert storage.read_records() == [{"later": True}]
    with closing(sqlite3.connect(path)) as connection:
        assert connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('index', 'trigger') ORDER BY name"
        ).fetchall() == [("payload_index",), ("reject_later",)]


@pytest.mark.parametrize("stage", ["INSERT", "COMMIT"])
@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_write_failure_rolls_back_closes_and_preserves_primary(
    tmp_path, monkeypatch, stage, cancel, cleanup_fails
):
    path = tmp_path / "reports.sqlite3"
    _seed_records(path, [(8, '{"old":true}')])
    failure = KeyboardInterrupt() if cancel else sqlite3.OperationalError("injected IO")
    if not cancel:
        failure.sqlite_errorcode = sqlite3.SQLITE_IOERR

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith(stage):
                raise failure
            result = super().execute(sql, *args, **kwargs)
            if cleanup_fails and sql == "ROLLBACK":
                raise sqlite3.OperationalError("rollback cleanup failed")
            return result

        def close(self):
            super().close()
            if cleanup_fails:
                raise sqlite3.OperationalError("close cleanup failed")

    connection = sqlite3.connect(path, isolation_level=None, factory=FailingConnection)
    storage = SqliteReportStorage(path)
    monkeypatch.setattr(storage, "_connect", lambda: connection)
    with pytest.raises(KeyboardInterrupt if cancel else OSError) as error:
        storage.write_records([{"new": True}])
    assert (error.value if cancel else error.value.__cause__) is failure
    if cleanup_fails:
        assert any("rollback cleanup failed" in note for note in error.value.__notes__)
        assert any("close cleanup failed" in note for note in error.value.__notes__)
    with pytest.raises(sqlite3.ProgrammingError):
        connection.cursor()
    assert SqliteReportStorage(path).read_records() == [{"old": True}]


def test_write_missing_parent_is_oserror_and_corrupt_database_is_valueerror(tmp_path):
    missing = tmp_path / "missing" / "reports.sqlite3"
    with pytest.raises(OSError) as error:
        SqliteReportStorage(missing).write_records([])
    assert isinstance(error.value.__cause__, sqlite3.Error)
    assert not missing.parent.exists()
    path = tmp_path / "corrupt.sqlite3"
    path.write_bytes(b"not a database" * 100)
    with pytest.raises(ValueError) as error:
        SqliteReportStorage(path).write_records([])
    assert isinstance(error.value.__cause__, sqlite3.Error)
    assert path.read_bytes() == b"not a database" * 100


def test_write_empty_new_database_closes_connection_after_commit(tmp_path, monkeypatch):
    path = tmp_path / "reports.sqlite3"
    storage = SqliteReportStorage(path)
    connect = storage._connect
    opened = []

    def capture_connection():
        connection = connect()
        opened.append(connection)
        return connection

    monkeypatch.setattr(storage, "_connect", capture_connection)
    storage.write_records([])
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].cursor()
    assert SqliteReportStorage(path).read_records() == []


@pytest.mark.parametrize(
    "code,expected",
    [(sqlite3.SQLITE_CORRUPT | (1 << 8), ValueError),
     (sqlite3.SQLITE_NOTADB, ValueError), (sqlite3.SQLITE_BUSY, OSError)],
)
def test_write_database_error_codes_preserve_cause(tmp_path, monkeypatch, code, expected):
    path = tmp_path / "reports.sqlite3"
    _seed_records(path, [(1, '{"old":true}')])
    failure = sqlite3.DatabaseError("injected transaction failure")
    failure.sqlite_errorcode = code

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == "DELETE FROM records":
                raise failure
            return super().execute(sql, *args, **kwargs)

    connection = sqlite3.connect(path, isolation_level=None, factory=FailingConnection)
    storage = SqliteReportStorage(path)
    monkeypatch.setattr(storage, "_connect", lambda: connection)
    with pytest.raises(expected) as error:
        storage.write_records([])
    assert error.value.__cause__ is failure
    assert SqliteReportStorage(path).read_records() == [{"old": True}]


def test_write_close_error_after_success_reports_oserror_with_committed_rows(
    tmp_path, monkeypatch
):
    path = tmp_path / "reports.sqlite3"
    _seed_records(path)
    failure = sqlite3.OperationalError("close failed")

    class CloseFailingConnection(sqlite3.Connection):
        def close(self):
            super().close()
            raise failure

    connection = sqlite3.connect(path, isolation_level=None, factory=CloseFailingConnection)
    storage = SqliteReportStorage(path)
    monkeypatch.setattr(storage, "_connect", lambda: connection)
    with pytest.raises(OSError) as error:
        storage.write_records([{"committed": True}])
    assert error.value.__cause__ is failure
    assert SqliteReportStorage(path).read_records() == [{"committed": True}]


def test_failed_first_write_leaves_readable_empty_history_and_allows_retry(
    tmp_path, monkeypatch
):
    path = tmp_path / "reports.sqlite3"
    original_connect = sqlite3.connect

    class FailingInsertConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql.startswith("INSERT"):
                raise sqlite3.OperationalError("first write failed")
            return super().execute(sql, *args, **kwargs)

    def connect(*args, **kwargs):
        return original_connect(*args, **kwargs, factory=FailingInsertConnection)

    monkeypatch.setattr(sqlite3, "connect", connect)
    with pytest.raises(OSError):
        SqliteReportStorage(path).write_records([{"first": True}])
    monkeypatch.undo()
    storage = SqliteReportStorage(path)
    assert storage.read_records() == []
    storage.write_records([{"retry": True}])
    assert storage.read_records() == [{"retry": True}]


@pytest.mark.skipif(os.name != "posix", reason="POSIX directory permissions required")
@pytest.mark.parametrize("existing", [False, True])
def test_write_readonly_directory_raises_oserror(tmp_path, existing):
    if os.geteuid() == 0:
        pytest.skip("root bypasses POSIX directory write permissions")
    directory = tmp_path / "readonly"
    directory.mkdir()
    path = directory / "reports.sqlite3"
    if existing:
        _seed_records(path, [(0, '{"old":true}')])
    before = {item.name: item.read_bytes() for item in directory.iterdir()}
    directory.chmod(0o500)
    try:
        with pytest.raises(OSError):
            SqliteReportStorage(path).write_records([])
        assert {item.name: item.read_bytes() for item in directory.iterdir()} == before
    finally:
        directory.chmod(0o700)
