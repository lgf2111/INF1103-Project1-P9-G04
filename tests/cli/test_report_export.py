"""Exercise the filtered preview and CSV export from the interactive menu."""

import csv
from unittest.mock import Mock

import pytest

from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage
from phishreport.io import IOManager
from phishreport.io.terminal import ConsoleTerminal
from phishreport.logic import LogicManager


def _run_menu(monkeypatch, history, answers):
    ai_manager = Mock()
    inputs = iter(["6", *answers, "7"])
    monkeypatch.setattr("builtins.input", lambda _: next(inputs))
    monkeypatch.setattr("phishreport.cli.main.AppLogging.setup", lambda: True)
    PhishReportApp(
        IOManager(ConsoleTerminal()),
        ai_manager,
        LogicManager(),
        DataManager(JsonReportStorage(history)),
    ).run()
    assert ai_manager.mock_calls == []


def test_cli_previews_and_exports_the_same_filtered_rows(tmp_path, monkeypatch, capsys):
    history = tmp_path / "history.json"
    JsonReportStorage(history).write_records([
        {"channel": "sms", "priority": "HIGH", "score": 95, "message": "First match"},
        {"channel": "email", "priority": "HIGH", "score": 100, "message": "Wrong channel"},
        {"channel": "sms", "priority": "LOW", "score": 10, "message": "Wrong priority"},
        {"channel": "sms", "priority": "HIGH", "score": 85, "message": "Second match"},
    ])
    original = history.read_bytes()
    destination = tmp_path / "selected reports.csv"

    _run_menu(monkeypatch, history, ["high", "sms", str(destination)])

    output = capsys.readouterr().out
    assert output.index("First match") < output.index("Second match")
    assert "Wrong channel" not in output and "Wrong priority" not in output
    assert "Exported 2 report(s) to CSV." in output
    assert "Bye!" in output
    with destination.open(encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    assert [(row["message"], row["score"]) for row in rows] == [
        ("First match", "95"), ("Second match", "85"),
    ]
    assert history.read_bytes() == original


@pytest.mark.parametrize(("history_text", "answers", "expected"), [
    ("[]", [], "No saved reports yet."),
    ('[{"channel": "sms"}]', ["", "email"], "No saved reports match."),
    ("invalid JSON", [], "Could not load local report history; existing file preserved."),
])
def test_cli_reports_history_state_before_asking_for_a_destination(
    tmp_path, monkeypatch, capsys, history_text, answers, expected,
):
    history = tmp_path / "history.json"
    history.write_text(history_text, encoding="utf-8")

    _run_menu(monkeypatch, history, answers)

    output = capsys.readouterr().out
    assert expected in output
    assert not list(tmp_path.glob("*.csv"))
    assert "Bye!" in output


def test_cli_handles_an_unwritable_export_destination(tmp_path, monkeypatch, capsys):
    history = tmp_path / "history.json"
    JsonReportStorage(history).write_records([{"message": "A saved report"}])
    destination = tmp_path / "missing folder" / "report.csv"

    _run_menu(monkeypatch, history, ["", "", str(destination)])

    output = capsys.readouterr().out
    assert "Could not export reports. Choose a new file in a writable folder." in output
    assert str(destination) not in output
    assert not destination.exists()
    assert "Bye!" in output


def test_cli_can_preview_and_skip_export(tmp_path, monkeypatch, capsys):
    history = tmp_path / "history.json"
    JsonReportStorage(history).write_records([{"message": "Preview only"}])

    _run_menu(monkeypatch, history, ["", "", ""])

    output = capsys.readouterr().out
    assert "Preview only" in output
    assert "Exported" not in output
    assert not list(tmp_path.glob("*.csv"))
    assert "Bye!" in output
