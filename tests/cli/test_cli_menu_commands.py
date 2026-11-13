"""Slash commands work through the real CLI menu and shared command workflow."""

from unittest.mock import Mock

import pytest

from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage
from phishreport.io import IOManager
from phishreport.io.check_command import CheckCommand
from phishreport.io.commands import CommandRouter
from phishreport.io.help_command import HelpCommand
from phishreport.logging_setup import AppLogging


@pytest.fixture
def menu_app(tmp_path, monkeypatch):
    monkeypatch.setattr(AppLogging, "setup", lambda: True)

    def build(answers):
        terminal = Mock()
        terminal.read.side_effect = answers
        ai = Mock(**{"assess.return_value": {"suspicious": True}})
        logic = Mock(**{"evaluate.return_value": {
            "score": 60, "priority": "MEDIUM", "reasons": [], "checklist": [],
        }})
        data = DataManager(JsonReportStorage(tmp_path / "reports.json"))
        app = PhishReportApp(IOManager(terminal), ai, logic, data, env_loader=Mock())
        return app, terminal, ai, logic, data

    return build


def test_menu_routes_help_and_check_through_shared_commands_and_saves_once(menu_app, monkeypatch):
    raw = "  /check   Mixed CASE  message\nTrailing spaces  "
    app, terminal, ai, logic, data = menu_app(["/help", raw, "no", "no", "no", "6"])
    routed = []
    checked = []
    helped = []
    original_route = CommandRouter.route
    original_check = CheckCommand.execute
    original_help = HelpCommand.execute

    def route(router, request):
        routed.append(request.text)
        return original_route(router, request)

    def check(command, request):
        checked.append(request.text)
        return original_check(command, request)

    def help_execute(command, request):
        helped.append(request.text)
        return original_help(command, request)

    monkeypatch.setattr(CommandRouter, "route", route)
    monkeypatch.setattr(CheckCommand, "execute", check)
    monkeypatch.setattr(HelpCommand, "execute", help_execute)

    app.run()

    assert routed == ["/help", raw]
    assert checked == ["Mixed CASE  message\nTrailing spaces  "]
    assert helped == [""]
    ai.assess.assert_called_once()
    logic.evaluate.assert_called_once()
    [report] = data.load(strict=True)
    assert report["message"] == checked[0]
    assert report["assessment_id"]
    assert report["result"]["score"] == 60
    assert any("/help:" in entry.args[0] for entry in terminal.write.call_args_list)
    terminal.write.assert_any_call("Bye!")
    assert terminal.read.call_count == 6


def test_menu_continues_after_usage_and_unknown_commands_then_assesses(menu_app):
    app, terminal, ai, logic, data = menu_app([
        "/check  ", "/unknown Content", "/CHECK Content", "/", "/check Valid Message",
        "no", "no", "no", "6",
    ])

    app.run()

    terminal.write.assert_any_call("Usage: /check <text>")
    ai.assess.assert_called_once()
    logic.evaluate.assert_called_once()
    [report] = data.load(strict=True)
    assert report["message"] == "Valid Message"
    terminal.write.assert_any_call("Bye!")


@pytest.mark.parametrize("error_type", [ValueError, RuntimeError])
def test_menu_continues_after_failed_command_and_saves_only_next_success(menu_app, error_type):
    app, terminal, ai, logic, data = menu_app([
        "/check Failed Message", "no", "no", "no",
        "/check Next Message", "no", "no", "no", "6",
    ])
    ai.assess.side_effect = [error_type("Assessment failed"), {"suspicious": True}]

    app.run()

    assert ai.assess.call_count == 2
    logic.evaluate.assert_called_once()
    [report] = data.load(strict=True)
    assert report["message"] == "Next Message"
    terminal.write.assert_any_call("Bye!")


def test_menu_numeric_manual_check_still_collects_and_assesses(menu_app):
    app, terminal, ai, logic, data = menu_app([
        "1", "chat", "", "Manual Message", "END", "no", "no", "no", "6",
    ])

    app.run()

    ai.assess.assert_called_once()
    logic.evaluate.assert_called_once()
    [report] = data.load(strict=True)
    assert report["message"] == "Manual Message"
    terminal.write.assert_any_call("Bye!")
