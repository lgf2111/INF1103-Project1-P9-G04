"""CLI status reports strict saved-history counts without assessing messages."""

from unittest.mock import Mock

import pytest

from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
from phishreport.io import IOManager
from phishreport.io.status_command import StatusCommand
from phishreport.logging_setup import AppLogging


@pytest.fixture
def status_app(tmp_path, monkeypatch):
    monkeypatch.setattr(AppLogging, "setup", lambda: True)

    def build(backend, count, answers):
        storage_type = JsonReportStorage if backend == "json" else SqliteReportStorage
        data = DataManager(storage_type(tmp_path / "history"))
        for number in range(count):
            data.save({
                "schema_version": 2, "channel": "chat", "message": f"Saved {number}",
                "result": {"score": 10, "priority": "LOW", "reasons": [], "checklist": []},
            })
        terminal = Mock()
        terminal.read.side_effect = answers
        io = IOManager(terminal)
        monkeypatch.setattr(io, "collect_input", Mock())
        monkeypatch.setattr(io, "build_record_from_message", Mock())
        monkeypatch.setattr(io, "collect_feedback", Mock())
        ai, logic, feedback = Mock(), Mock(), Mock()
        monkeypatch.setattr(data, "save", Mock(wraps=data.save))
        app = PhishReportApp(io, ai, logic, data, env_loader=Mock(), feedback_service=feedback)
        return app, terminal, io, ai, logic, data, feedback

    return build


@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize("count", [0, 2])
def test_cli_menu_status_uses_shared_command_and_strict_saved_count(
    status_app, monkeypatch, backend, count,
):
    app, terminal, io, ai, logic, data, feedback = status_app(backend, count, ["/status", "6"])
    executions = []
    original_execute = StatusCommand.execute
    load = Mock(wraps=data.load)
    monkeypatch.setattr(data, "load", load)

    def execute(command, request):
        executions.append(request)
        return original_execute(command, request)

    monkeypatch.setattr(StatusCommand, "execute", execute)

    app.run()

    terminal.write.assert_any_call(f"Session: CLI conversation active\nSaved reports: {count}")
    assert len(executions) == 1 and executions[0].channel == "cli"
    assert load.call_count == 2
    assert all(entry.kwargs == {"strict": True} for entry in load.call_args_list)
    io.collect_input.assert_not_called()
    io.build_record_from_message.assert_not_called()
    io.collect_feedback.assert_not_called()
    ai.assess.assert_not_called()
    logic.evaluate.assert_not_called()
    feedback.submit.assert_not_called()
    data.save.assert_not_called()
    assert len(data.load(strict=True)) == count


@pytest.mark.parametrize("error_type", [OSError, ValueError])
def test_cli_status_history_failure_is_sanitized_and_menu_continues(
    status_app, monkeypatch, error_type,
):
    app, terminal, io, ai, logic, data, feedback = status_app(
        "json", 1, ["/status", "/help", "6"],
    )
    original_load = data.load
    history = original_load(strict=True)
    monkeypatch.setattr(data, "load", Mock(side_effect=[history, error_type("PRIVATE_ERROR")]))

    app.run()

    terminal.write.assert_any_call(
        "Could not load local report history; existing file preserved."
    )
    output = "\n".join(str(entry.args) for entry in terminal.write.call_args_list)
    assert "PRIVATE_ERROR" not in output and "Saved reports: 0" not in output
    assert "/help:" in output and "/status:" in output
    terminal.write.assert_any_call("Bye!")
    assert original_load(strict=True) == history
    ai.assess.assert_not_called()
    data.save.assert_not_called()
    feedback.submit.assert_not_called()


def test_cli_help_lists_status_once_without_loading_history(status_app, monkeypatch):
    app, terminal, io, ai, logic, data, feedback = status_app("json", 0, [])
    load = Mock(side_effect=AssertionError("Help must not read history"))
    monkeypatch.setattr(data, "load", load)

    app.check_message(command_text="/help")

    help_text = terminal.write.call_args.args[0]
    assert help_text.count("/status:") == 1
    load.assert_not_called()
    ai.assess.assert_not_called()
    data.save.assert_not_called()
