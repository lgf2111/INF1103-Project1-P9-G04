"""Feedback is stored beside the report file unless explicitly configured."""

import pytest

from phishreport.both import build_bot_application, build_cli_app
from phishreport.data import DataManager, JsonReportStorage
from phishreport.data.factory import resolve_feedback_path

TOKEN = "123456:AAExampleTokenNotReal_0123456789abcdefg"


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch):
    monkeypatch.delenv("PHISHREPORT_FEEDBACK_PATH", raising=False)
    monkeypatch.delenv("PHISHREPORT_REPORTS_PATH", raising=False)


def test_feedback_defaults_beside_the_configured_reports_file(tmp_path, monkeypatch):
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", str(tmp_path / "x" / "reports.json"))
    assert resolve_feedback_path() == str(tmp_path / "x" / "feedback.json")


def test_explicit_feedback_path_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", str(tmp_path / "reports.json"))
    explicit = tmp_path / "elsewhere" / "feedback.json"
    monkeypatch.setenv("PHISHREPORT_FEEDBACK_PATH", str(explicit))
    assert resolve_feedback_path() == str(explicit)


def test_without_configuration_feedback_keeps_the_relative_default():
    assert resolve_feedback_path() == "feedback.json"


def test_both_entry_points_share_the_feedback_file_beside_the_reports(tmp_path, monkeypatch):
    reports = tmp_path / "data" / "reports.json"
    reports.parent.mkdir()
    monkeypatch.setenv("PHISHREPORT_REPORTS_PATH", str(reports))
    monkeypatch.setenv("PHISHREPORT_GMAIL_PATH", str(tmp_path / "gmail.json"))
    manager = DataManager(JsonReportStorage(reports))

    cli_app = build_cli_app(manager)
    bot_app = build_bot_application(manager, TOKEN)

    cli_store = cli_app._feedback_service._store
    bot_manager = bot_app.handlers[0][0].callback.__self__
    bot_store = bot_manager._feedback_service._store

    expected = reports.parent / "feedback.json"
    assert cli_store._path == expected
    assert bot_store._path == expected
    assert cli_store._path == bot_store._path
