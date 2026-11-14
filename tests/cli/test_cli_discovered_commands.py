"""Real drop-in command files extend CLI routing through declared policies."""

import importlib
import sys
from unittest.mock import Mock

import pytest

from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage
from phishreport.io import IOManager, command_plugins
from phishreport.logging_setup import AppLogging

MODULE = "phishreport.io.command_plugins.zz_cli_extension_probe"


@pytest.fixture
def plugin_file(tmp_path, monkeypatch):
    path = tmp_path / "plugins"
    path.mkdir()
    monkeypatch.setattr(command_plugins, "__path__", [*command_plugins.__path__, str(path)])

    def install(body, *, policy="CommandPolicy()", factory_body="return ExtensionCommand()"):
        source = (
            "from phishreport.io.commands import Command, CommandPolicy, CommandReply\n"
            "from phishreport.io.check_command import CheckCommand\n"
            "FAILURE = ValueError('PRIVATE_FACTORY')\n"
            "class ExtensionCommand(Command):\n"
            "    name = 'extension_probe'\n"
            "    help_text = 'Temporary drop-in command'\n"
            f"    policy = {policy}\n"
            "    def execute(self, request):\n"
            + "\n".join("        " + line for line in body.splitlines())
            + "\ndef create_command(capabilities):\n"
            + "\n".join("    " + line for line in factory_body.splitlines()) + "\n"
        )
        (path / "zz_cli_extension_probe.py").write_text(source, encoding="utf-8")
        importlib.invalidate_caches()

    yield install
    sys.modules.pop(MODULE, None)
    attribute = MODULE.rsplit(".", 1)[-1]
    if hasattr(command_plugins, attribute):
        delattr(command_plugins, attribute)
    importlib.invalidate_caches()


@pytest.fixture
def extension_app(tmp_path, monkeypatch):
    monkeypatch.setattr(AppLogging, "setup", lambda: True)
    terminal = Mock()
    io = IOManager(terminal)
    ai = Mock(**{"assess.return_value": {"suspicious": True}})
    logic = Mock(**{"evaluate.return_value": {
        "score": 60, "priority": "MEDIUM", "reasons": [], "checklist": [],
    }})
    data = DataManager(JsonReportStorage(tmp_path / "reports.json"))
    monkeypatch.setattr(data, "save", Mock(wraps=data.save))
    feedback = Mock()
    app = PhishReportApp(io, ai, logic, data, env_loader=Mock(), feedback_service=feedback)
    return app, terminal, ai, logic, data, feedback


def test_drop_in_file_runs_from_real_menu_and_appears_in_help_without_ai(
    plugin_file, extension_app,
):
    plugin_file("return CommandReply('Echo: ' + request.text, 'text')")
    app, terminal, ai, logic, data, feedback = extension_app
    terminal.read.side_effect = [" /extension_probe   Mixed CASE ", "/help", "6"]

    app.run()

    terminal.write.assert_any_call("Echo: Mixed CASE ")
    output = "\n".join(str(entry.args) for entry in terminal.write.call_args_list)
    assert "/extension_probe: Temporary drop-in command" in output
    assert terminal.read.call_count == 3
    ai.assess.assert_not_called()
    logic.evaluate.assert_not_called()
    data.save.assert_not_called()
    feedback.submit.assert_not_called()


def test_ordinary_reply_kind_cannot_enter_assessment_persistence(plugin_file, extension_app):
    plugin_file("return CommandReply('Assessment-shaped ordinary reply', 'assessment')")
    app, terminal, ai, logic, data, feedback = extension_app

    app.check_message(command_text="/extension_probe")

    terminal.write.assert_called_once_with("Assessment-shaped ordinary reply")
    data.save.assert_not_called()
    feedback.submit.assert_not_called()
    ai.assess.assert_not_called()


@pytest.mark.parametrize("error_type", ["OSError", "ValueError", "RuntimeError"])
@pytest.mark.parametrize("failure,expected", [
    ("command", "Sorry, the command failed. Please try again."),
    ("history", "Could not load local report history; existing file preserved."),
])
def test_drop_in_expected_errors_follow_policy_without_concrete_type_checks(
    plugin_file, extension_app, error_type, failure, expected,
):
    plugin_file(
        f"raise {error_type}('PRIVATE_ERROR')", policy=f"CommandPolicy(failure='{failure}')",
    )
    app, terminal, ai, logic, data, feedback = extension_app
    terminal.read.side_effect = ["/extension_probe", "/help", "6"]

    app.run()

    terminal.write.assert_any_call(expected)
    output = "\n".join(str(entry.args) for entry in terminal.write.call_args_list)
    assert "PRIVATE_ERROR" not in output and "/help:" in output
    ai.assess.assert_not_called()
    data.save.assert_not_called()
    feedback.submit.assert_not_called()


@pytest.mark.parametrize("error_type", ["ValueError", "RuntimeError", "OSError"])
def test_custom_assessment_policy_retains_assessment_error_presentation(
    plugin_file, extension_app, error_type,
):
    plugin_file(
        f"raise {error_type}('Assessment unavailable')",
        policy="CommandPolicy(execution='assessment', failure='assessment')",
    )
    app, terminal, ai, logic, data, feedback = extension_app
    app._error_translator = Mock(**{"translate.return_value": "Assessment temporarily unavailable"})

    app.check_message(command_text="/extension_probe")

    text = terminal.write.call_args.args[0]
    if error_type == "OSError":
        assert text == "Sorry, the check failed. Please try again."
    elif error_type == "ValueError":
        assert text == "Sorry, the check failed: Assessment unavailable"
    else:
        app._error_translator.translate.assert_called_once()
        assert text == "Assessment temporarily unavailable"
    data.save.assert_not_called()


@pytest.mark.parametrize("error_type", ["KeyError", "TypeError"])
def test_programming_errors_surface_from_discovered_command(plugin_file, extension_app, error_type):
    plugin_file(f"raise {error_type}('Programming error')")
    app, terminal, ai, logic, data, feedback = extension_app
    expected = KeyError if error_type == "KeyError" else TypeError

    with pytest.raises(expected):
        app.check_message(command_text="/extension_probe")

    data.save.assert_not_called()


def test_factory_failure_propagates_outside_assessment_handlers(plugin_file, extension_app):
    plugin_file("return CommandReply('Unused', 'text')", factory_body="raise FAILURE")
    app, terminal, ai, logic, data, feedback = extension_app
    module = importlib.import_module(MODULE)

    with pytest.raises(ValueError) as caught:
        app.check_message(command_text="/help")

    assert caught.value is module.FAILURE
    terminal.write.assert_not_called()
    ai.assess.assert_not_called()
    data.save.assert_not_called()


def test_custom_assessment_policy_enters_existing_save_workflow(plugin_file, extension_app):
    plugin_file(
        "return self.check.execute(request)",
        policy="CommandPolicy(execution='assessment', failure='assessment')",
        factory_body=(
            "command = ExtensionCommand()\n"
            "command.check = CheckCommand(\n"
            "    capabilities.prepare_record, capabilities.assess_record)\n"
            "return command"
        ),
    )
    app, terminal, ai, logic, data, feedback = extension_app
    app._feedback_service = None
    terminal.read.side_effect = ["no", "no", "no"]

    app.check_message(command_text="/extension_probe Preserved assessment payload ")

    ai.assess.assert_called_once()
    logic.evaluate.assert_called_once()
    data.save.assert_called_once()
    [saved] = data.load(strict=True)
    assert saved["message"] == "Preserved assessment payload "
    assert saved["result"]["score"] == 60 and saved["assessment_id"]
