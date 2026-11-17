"""The CLI must save the exposure answers it collected, not discard them."""

from unittest.mock import Mock

from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage
from phishreport.io import IOManager
from phishreport.io.terminal import ConsoleTerminal
from phishreport.logging_setup import AppLogging
from phishreport.logic import LogicManager


def test_cli_saves_exposure_answers_and_summary_counts_them(tmp_path, monkeypatch, capsys):
    """A click and a disclosed password reach the saved reports and the summary."""
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
    # Two manual checks, each followed by its post-verdict checklist answer:
    # one clicked link, one shared password. The final two blanks keep the
    # summary filter unfiltered.
    answers = iter(
        [
            "Visit https://example.test/login now.",
            "END",
            "1",
            "A fictional message asks for a password.",
            "END",
            "3",
            "",
            "",
        ]
    )
    monkeypatch.setattr("builtins.input", lambda _: next(answers))

    app.check_message(app._io_manager.collect_input())
    app.check_message(app._io_manager.collect_input())
    app.summarize_reports()

    clicked, disclosed = data_manager.load(strict=True)
    assert clicked["schema_version"] == 3
    assert clicked["assessment_id"]
    assert clicked["exposure"] == {
        "clicked": True,
        "downloaded": False,
        "submitted_category": None,
        "disclosure_answered": True,
    }
    assert disclosed["exposure"] == {
        "clicked": False,
        "downloaded": False,
        "submitted_category": "password",
        "disclosure_answered": True,
    }
    assert "assessment_id" not in clicked["result"]
    assert "assessment_id" not in disclosed["result"]

    output = capsys.readouterr().out
    assert "Clicked a link: 1" in output
    assert "Submitted a password or code: 1" in output
