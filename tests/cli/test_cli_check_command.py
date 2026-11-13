"""CLI command assessment reuses the shared command and existing save workflow."""

from unittest.mock import Mock

import pytest

from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage
from phishreport.io.check_command import CheckCommand


@pytest.fixture
def command_app(tmp_path):
    io = Mock()
    io.build_record_from_message.side_effect = lambda text, channel: {
        "channel": channel,
        "message": text,
    }
    io.collect_feedback.return_value = {
        "category": "incorrect_priority",
        "comment": "Internal test",
        "corrected_priority": "LOW",
    }
    ai = Mock(**{"assess.return_value": {"suspicious": True}})
    logic = Mock(
        **{"evaluate.return_value": {
            "score": 60, "priority": "MEDIUM", "reasons": [], "checklist": [],
        }}
    )
    data = DataManager(JsonReportStorage(tmp_path / "reports.json"))
    feedback = Mock()
    app = PhishReportApp(io, ai, logic, data, feedback_service=feedback)
    return app, io, ai, logic, data, feedback


def test_cli_command_uses_shared_execute_once_preserves_text_and_saves_feedback(
    command_app, monkeypatch,
):
    app, io, ai, logic, data, feedback = command_app
    original_execute = CheckCommand.execute
    executions = []

    def execute(command, request):
        executions.append(request)
        return original_execute(command, request)

    monkeypatch.setattr(CheckCommand, "execute", execute)
    text = "URGENT  Payment\nKeep Case and trailing spaces  "

    app.check_message(command_text=text)

    assert len(executions) == 1
    assert executions[0].text == text
    assert executions[0].channel == "cli"
    io.collect_input.assert_not_called()
    io.build_record_from_message.assert_called_once_with(text, channel="chat")
    record = {"channel": "chat", "message": text}
    ai.assess.assert_called_once_with(record)
    logic.evaluate.assert_called_once_with({**record, "ai": {"suspicious": True}})
    [saved] = data.load(strict=True)
    result = io.display_result.call_args.args[0]
    assert saved["schema_version"] == 3
    assert saved["message"] == text
    assert saved["assessment_id"] == result["assessment_id"]
    assert result["assessment_id"]
    assert "assessment_id" not in saved["result"]
    feedback.submit.assert_called_once_with(
        assessment_id=result["assessment_id"], assessment_result=result,
        **io.collect_feedback.return_value,
    )
    assert all(call.args[0] != "Assessment ready." for call in io.show_message.call_args_list)


@pytest.mark.parametrize("text", ["", " \t\n "])
def test_cli_empty_command_shows_usage_before_any_prompts_or_assessment(command_app, text):
    app, io, ai, logic, data, feedback = command_app

    app.check_message(command_text=text)

    io.show_message.assert_called_once_with("Usage: /check <text>")
    io.collect_input.assert_not_called()
    io.build_record_from_message.assert_not_called()
    io.collect_feedback.assert_not_called()
    io.display_result.assert_not_called()
    ai.assess.assert_not_called()
    logic.evaluate.assert_not_called()
    feedback.submit.assert_not_called()
    assert data.load(strict=True) == []


@pytest.mark.parametrize("stage", ["builder", "assessment"])
@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_cli_command_failure_keeps_history_and_stops_before_save_or_feedback(
    command_app, stage, error_type,
):
    app, io, ai, logic, data, feedback = command_app
    history = [{
        "schema_version": 2, "channel": "chat", "message": "Prior saved report",
        "result": {"score": 10, "priority": "LOW", "reasons": [], "checklist": []},
    }]
    data.save(history[0])
    if stage == "builder":
        io.build_record_from_message.side_effect = error_type("Check failed")
    else:
        ai.assess.side_effect = error_type("Check failed")

    app.check_message(command_text="Message")

    assert data.load(strict=True) == history
    io.collect_input.assert_not_called()
    io.display_result.assert_not_called()
    io.collect_feedback.assert_not_called()
    feedback.submit.assert_not_called()
    logic.evaluate.assert_not_called()
    io.show_message.assert_called_once()
    if stage == "builder":
        ai.assess.assert_not_called()


def test_cli_command_storage_failure_still_displays_assessment_without_feedback(
    command_app, monkeypatch,
):
    app, io, ai, logic, data, feedback = command_app
    save = Mock(side_effect=OSError("Read-only destination"))
    monkeypatch.setattr(data, "save", save)

    app.check_message(command_text="Payment request")

    ai.assess.assert_called_once()
    logic.evaluate.assert_called_once()
    save.assert_called_once()
    io.display_result.assert_called_once()
    io.show_message.assert_called_once_with(
        "Could not save the local report; existing history preserved."
    )
    io.collect_feedback.assert_not_called()
    feedback.submit.assert_not_called()
    assert data.load(strict=True) == []
