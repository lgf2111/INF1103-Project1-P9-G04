"""Explicit JSON migration preserves history and commits all records together."""

import os
import sqlite3
from contextlib import closing

import pytest

from phishreport.data.migration import migrate_json_to_sqlite
from phishreport.data.sqlite_storage import SqliteReportStorage


def test_migration_preserves_duplicates_unicode_legacy_and_source_bytes(tmp_path):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    original = (
        b' [ {"unknown": "caf\xc3\xa9", "nested": [true, null]},\n'
        b' {"same": 1}, {"same": 1} ]\n'
    )
    source.write_bytes(original)
    assert migrate_json_to_sqlite(source, target) == 3
    assert migrate_json_to_sqlite(source, target) == 0
    assert SqliteReportStorage(target).read_records() == [
        {"unknown": "café", "nested": [True, None]}, {"same": 1}, {"same": 1}
    ]
    assert source.read_bytes() == original


def test_empty_source_creates_readable_empty_target(tmp_path):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    source.write_text("[]", encoding="utf-8")
    assert migrate_json_to_sqlite(str(source), str(target)) == 0
    assert target.is_file()
    assert SqliteReportStorage(target).read_records() == []


@pytest.mark.parametrize("content", [None, b"{", b"{}", b"[1]", b'[{"x":1,"x":2}]',
                                     b'[{"x":NaN}]', b'[{"x":"\\ud800"}]', b"\xff"])
@pytest.mark.parametrize("existing", [False, True])
def test_invalid_source_does_not_touch_target(tmp_path, content, existing):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    if content is not None:
        source.write_bytes(content)
    if existing:
        SqliteReportStorage(target).write_records([{"old": True}])
    before = {item.name: item.read_bytes() for item in tmp_path.iterdir()}
    with pytest.raises(FileNotFoundError if content is None else ValueError):
        migrate_json_to_sqlite(source, target)
    assert {item.name: item.read_bytes() for item in tmp_path.iterdir()} == before


@pytest.mark.parametrize("alias", ["normalized", "hardlink", "symlink"])
def test_aliases_rejected_without_changing_source(tmp_path, alias):
    source = tmp_path / "reports.json"
    source.write_bytes(b"[{}]")
    target = tmp_path / "alias"
    if alias == "normalized":
        target = tmp_path / "." / "reports.json"
    elif alias == "hardlink":
        try:
            os.link(source, target)
        except OSError:
            pytest.skip("Creating hardlinks is unavailable in this environment")
    else:
        try:
            target.symlink_to(source)
        except OSError:
            pytest.skip("Creating symlinks requires platform privileges")
    with pytest.raises(ValueError):
        migrate_json_to_sqlite(source, target)
    assert source.read_bytes() == b"[{}]"


@pytest.mark.parametrize("record", [{"x": False}, {"x": 1}, {"x": 1.0}])
def test_different_nonempty_target_is_preserved_including_json_types(tmp_path, record):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    source.write_text('[{"x":true}]', encoding="utf-8")
    SqliteReportStorage(target).write_records([record])
    with pytest.raises(ValueError):
        migrate_json_to_sqlite(source, target)
    assert SqliteReportStorage(target).read_records() == [record]


def test_identical_target_ignores_object_key_order_and_whitespace(tmp_path):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    source.write_text('[{"b": [1], "a":true}]', encoding="utf-8")
    SqliteReportStorage(target).write_records([{"a": True, "b": [1]}])
    assert migrate_json_to_sqlite(source, target) == 0


@pytest.mark.parametrize("payload", ["[]", '{"x":NaN}', '{"x":1,"x":2}', b"{}", None])
def test_malformed_target_payload_is_rejected_and_preserved(tmp_path, payload):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    source.write_text("[]", encoding="utf-8")
    SqliteReportStorage(target).write_records([])
    with closing(sqlite3.connect(target)) as connection:
        connection.execute("INSERT INTO records VALUES (4, ?)", (payload,))
        connection.commit()
    with pytest.raises(ValueError):
        migrate_json_to_sqlite(source, target)
    with closing(sqlite3.connect(target)) as connection:
        assert connection.execute("SELECT payload FROM records").fetchall() == [(payload,)]


@pytest.mark.parametrize("schema", ["CREATE TABLE other(x)",
    "CREATE TABLE records(position INTEGER PRIMARY KEY DESC, payload TEXT)",
    "CREATE TABLE records(position INTEGER PRIMARY KEY, payload TEXT, extra TEXT)"])
def test_incompatible_target_schema_is_rejected(tmp_path, schema):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    source.write_text("[]", encoding="utf-8")
    with closing(sqlite3.connect(target)) as connection:
        connection.execute(schema)
        connection.commit()
    with pytest.raises(ValueError):
        migrate_json_to_sqlite(source, target)


def test_later_insert_trigger_failure_rolls_back_all_records(tmp_path):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    source.write_text('[{"first":1},{"second":2}]', encoding="utf-8")
    SqliteReportStorage(target).write_records([])
    with closing(sqlite3.connect(target)) as connection:
        connection.execute("CREATE TRIGGER reject_later BEFORE INSERT ON records "
                           "WHEN NEW.position = 1 BEGIN SELECT RAISE(ABORT, 'later'); END")
        connection.commit()
    with pytest.raises(OSError) as error:
        migrate_json_to_sqlite(source, target)
    assert isinstance(error.value.__cause__, sqlite3.IntegrityError)
    assert SqliteReportStorage(target).read_records() == []


@pytest.mark.parametrize("stage", ["later_insert", "COMMIT"])
@pytest.mark.parametrize("cleanup_fails", [False, True])
def test_first_failure_rolls_back_closes_and_allows_retry(
    tmp_path, monkeypatch, stage, cleanup_fails
):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    source.write_text('[{"first":1},{"second":2}]', encoding="utf-8")
    original_connect = sqlite3.connect
    opened = []
    failure = sqlite3.OperationalError("injected failure")
    failure.sqlite_errorcode = sqlite3.SQLITE_IOERR

    class FailingConnection(sqlite3.Connection):
        def execute(self, sql, *args, **kwargs):
            if sql == stage or (stage == "later_insert" and sql.startswith("INSERT")
                                and args[0][0] == 1):
                raise failure
            result = super().execute(sql, *args, **kwargs)
            if cleanup_fails and sql == "ROLLBACK":
                raise sqlite3.OperationalError("rollback cleanup failed")
            return result

        def close(self):
            super().close()
            if cleanup_fails:
                raise sqlite3.OperationalError("close cleanup failed")

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs, factory=FailingConnection)
        opened.append(connection)
        return connection

    with monkeypatch.context() as patch:
        patch.setattr(sqlite3, "connect", connect)
        with pytest.raises(OSError) as error:
            migrate_json_to_sqlite(source, target)
        assert error.value.__cause__ is failure
        if cleanup_fails:
            assert len(error.value.__notes__) == 2
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].cursor()
    assert SqliteReportStorage(target).read_records() == []
    assert migrate_json_to_sqlite(source, target) == 2


def test_corrupt_database_and_missing_parent_preserve_source(tmp_path):
    source = tmp_path / "reports.json"
    source.write_bytes(b"[{}]")
    corrupt = tmp_path / "corrupt.sqlite3"
    corrupt.write_bytes(b"not a database" * 100)
    with pytest.raises(ValueError) as error:
        migrate_json_to_sqlite(source, corrupt)
    assert isinstance(error.value.__cause__, sqlite3.Error)
    assert corrupt.read_bytes() == b"not a database" * 100
    with pytest.raises(OSError) as error:
        migrate_json_to_sqlite(source, tmp_path / "missing" / "reports.sqlite3")
    assert isinstance(error.value.__cause__, sqlite3.Error)
    assert source.read_bytes() == b"[{}]"


def test_invalid_utf8_target_text_is_valueerror(tmp_path):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    source.write_text("[]", encoding="utf-8")
    SqliteReportStorage(target).write_records([])
    with closing(sqlite3.connect(target)) as connection:
        connection.execute("INSERT INTO records VALUES (0, CAST(x'ff' AS TEXT))")
        connection.commit()
    with pytest.raises(ValueError) as error:
        migrate_json_to_sqlite(source, target)
    assert isinstance(error.value.__cause__, UnicodeError)


def test_close_failure_reports_oserror_after_successful_commit(tmp_path, monkeypatch):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    source.write_text('[{"saved":true}]', encoding="utf-8")
    SqliteReportStorage(target).write_records([])
    failure = sqlite3.OperationalError("close failed")

    class CloseFailingConnection(sqlite3.Connection):
        def close(self):
            super().close()
            raise failure

    connection = sqlite3.connect(target, isolation_level=None, factory=CloseFailingConnection)
    monkeypatch.setattr(SqliteReportStorage, "_connect", lambda self: connection)
    with pytest.raises(OSError) as error:
        migrate_json_to_sqlite(source, target)
    assert error.value.__cause__ is failure
    monkeypatch.undo()
    assert SqliteReportStorage(target).read_records() == [{"saved": True}]


@pytest.mark.parametrize("repeat", [False, True])
def test_success_uses_one_connection_and_closes_it(tmp_path, monkeypatch, repeat):
    source = tmp_path / "reports.json"
    target = tmp_path / "reports.sqlite3"
    source.write_text('[{"x":1}]', encoding="utf-8")
    if repeat:
        migrate_json_to_sqlite(source, target)
    original = SqliteReportStorage._connect
    opened = []

    def capture(self):
        connection = original(self)
        opened.append(connection)
        return connection

    monkeypatch.setattr(SqliteReportStorage, "_connect", capture)
    assert migrate_json_to_sqlite(source, target) == (0 if repeat else 1)
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].cursor()
