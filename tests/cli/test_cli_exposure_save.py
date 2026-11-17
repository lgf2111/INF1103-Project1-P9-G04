"""The CLI must save the exposure answers it collected, not discard them."""

from unittest.mock import Mock

from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage
from phishreport.io import IOManager
from phishreport.io.terminal import ConsoleTerminal
from phishreport.logging_setup import AppLogging
from phishreport.logic import LogicManager


def test_cli_saves_exposure_answers_and_summary_counts_them(tmp_path, monkeypatch, capsys):
    """A click and a disclosed password reach the saved report and the summary."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(AppLogging, "setup", lambda: True)
    findings = {
        "credential_request": True,
        "suspicious": True,
        "insufficient_context": False,
    }
    ai_manager = Mock(**{"assess.return_value": findings})
    data_manager = DataManager(JsonReportStorage(tmp_path / "reports.json"))
    app = PhishReportApp(
        IOManager(ConsoleTerminal()), ai_manager, LogicManager(), data_manager
    )
    # Manual input: link yes, file no, clicked yes, password disclosed.
    answers = iter(
        [
            "chat",
            "",
            "A fictional message asks for a password.",
            "END",
            "yes",
            "https://example.test/login",
            "no",
            "yes",
            "password",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    app.check_message(app._io_manager.collect_input())
    app.summarize_reports()

    saved, = data_manager.load(strict=True)
    assert saved["schema_version"] == 3
    assert saved["assessment_id"]
    assert saved["exposure"] == {
        "clicked": True,
        "downloaded": False,
        "submitted_category": "password",
        "disclosure_answered": True,
    }
    assert "assessment_id" not in saved["result"]

    output = capsys.readouterr().out
    assert "Clicked a link: 1" in output
    assert "Submitted a password or code: 1" in output
