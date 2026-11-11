"""Environment selection and path safety for report storage composition."""

from pathlib import Path

import pytest

from phishreport.data.json_storage import JsonReportStorage
from phishreport.data.sqlite_storage import SqliteReportStorage
from phishreport.data.storage import ReportStorage


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch, tmp_path):
    monkeypatch.delenv("PHISHREPORT_STORAGE", raising=False)
    monkeypatch.delenv("PHISHREPORT_REPORTS_PATH", raising=False)
    monkeypatch.chdir(tmp_path)


def test_default_is_json_with_default_history_path():
    from phishreport.data.factory import create_report_storage

    Path("reports.json").write_text('[{"default":true}]', encoding="utf-8")
    storage = create_report_storage()
    assert isinstance(storage, ReportStorage)
    assert isinstance(storage, JsonReportStorage)
    assert storage.read_records() == [{"default": True}]


@pytest.mark.parametrize(
    "selector, expected_type, expected_path",
    [("json", JsonReportStorage, "reports.json"),
     ("sqlite", SqliteReportStorage, "reports.sqlite3")],
)
def test_explicit_selector_uses_default_path(monkeypatch, selector, expected_type, expected_path):
    from phishreport.data.factory import create_report_storage

    monkeypatch.setenv("PHISHREPORT_STORAGE", selector)
    storage = create_report_storage()
    assert isinstance(storage, expected_type)
    storage.write_records([{"selected": selector}])
    assert expected_type(expected_path).read_records() == [{"selected": selector}]


@pytest.mark.parametrize("selector", ["", " ", "JSON", "SQLite", " sqlite", "json ", "yaml"])
def test_invalid_selector_is_rejected_clearly(monkeypatch, selector):
    from phishreport.data.factory import create_report_storage

    monkeypatch.setenv("PHISHREPORT_STORAGE", selector)
    with pytest.raises(ValueError, match="PHISHREPORT_STORAGE.*json.*sqlite"):
        create_report_storage()


@pytest.mark.parametrize(
    "selector, configured_path, expected_path",
    [("json", "archive/custom.json", "archive/custom.json"),
     ("sqlite", "archive/custom.json", "archive/custom.sqlite3"),
     ("sqlite", "archive/custom.backup.json", "archive/custom.backup.sqlite3"),
     ("sqlite", "archive/history", "archive/history.sqlite3")],
)
def test_reports_path_controls_selected_destination(
    monkeypatch, selector, configured_path, expected_path
):
    from phishreport.data.factory import create_report_storage

    Path("archive").mkdir()
    monkeypatch.setenv("PHISHREPORT_STORAGE", selector)
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", configured_path)
    storage = create_report_storage()
    storage.write_records([{"custom": True}])
    assert storage.read_records() == [{"custom": True}]
    assert Path(expected_path).is_file()
    assert not Path("reports.json").exists()
    assert not Path("reports.sqlite3").exists()


@pytest.mark.parametrize("selector", ["json", "sqlite"])
def test_construction_creates_no_files_or_parent_directories(monkeypatch, tmp_path, selector):
    from phishreport.data.factory import create_report_storage

    monkeypatch.setenv("PHISHREPORT_STORAGE", selector)
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", "missing/reports.json")
    create_report_storage()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize("selector", ["json", "sqlite"])
def test_relative_paths_follow_operation_time_working_directory(monkeypatch, tmp_path, selector):
    from phishreport.data.factory import create_report_storage

    monkeypatch.setenv("PHISHREPORT_STORAGE", selector)
    storage = create_report_storage()
    other = tmp_path / "other"
    other.mkdir()
    monkeypatch.chdir(other)
    storage.write_records([{"moved": True}])
    assert storage.read_records() == [{"moved": True}]
    assert sorted(item.name for item in tmp_path.iterdir()) == ["other"]
    assert (other / ("reports.json" if selector == "json" else "reports.sqlite3")).is_file()


def test_environment_is_read_for_each_call(monkeypatch):
    from phishreport.data.factory import create_report_storage

    first = create_report_storage()
    monkeypatch.setenv("PHISHREPORT_STORAGE", "sqlite")
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", "changed.json")
    second = create_report_storage()
    assert isinstance(first, JsonReportStorage)
    assert isinstance(second, SqliteReportStorage)
    second.write_records([{"fresh": True}])
    assert SqliteReportStorage("changed.sqlite3").read_records() == [{"fresh": True}]
    assert first.read_records() == []


def test_sqlite_rejects_identical_source_and_destination_without_creating_it(monkeypatch):
    from phishreport.data.factory import create_report_storage

    monkeypatch.setenv("PHISHREPORT_STORAGE", "sqlite")
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", "reports.sqlite3")
    with pytest.raises(ValueError, match="(?i)(alias|distinct|same)"):
        create_report_storage()
    assert not Path("reports.sqlite3").exists()


@pytest.mark.parametrize("link_kind", ["symlink", "hardlink"])
def test_sqlite_rejects_existing_source_destination_alias(monkeypatch, tmp_path, link_kind):
    from phishreport.data.factory import create_report_storage

    source = tmp_path / "reports.json"
    destination = tmp_path / "reports.sqlite3"
    source.write_bytes(b"preserve source")
    try:
        if link_kind == "symlink":
            destination.symlink_to(source)
        else:
            destination.hardlink_to(source)
    except (OSError, NotImplementedError) as error:
        pytest.skip(f"{link_kind} unavailable: {error}")
    monkeypatch.setenv("PHISHREPORT_STORAGE", "sqlite")
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", str(source))
    with pytest.raises(ValueError, match="(?i)(alias|distinct|same)"):
        create_report_storage()
    assert source.read_bytes() == destination.read_bytes() == b"preserve source"


@pytest.mark.parametrize("operation", ["resolve", "samefile"])
def test_sqlite_does_not_hide_alias_check_permission_errors(monkeypatch, operation):
    from phishreport.data.factory import create_report_storage

    failure = PermissionError("alias check denied")

    def denied(self, *args, **kwargs):
        raise failure

    monkeypatch.setenv("PHISHREPORT_STORAGE", "sqlite")
    monkeypatch.setattr(Path, operation, denied)
    with pytest.raises(PermissionError) as error:
        create_report_storage()
    assert error.value is failure
