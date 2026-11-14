"""The Help factory keeps the discovery catalog live without executing services."""

import importlib
import sys
from unittest.mock import Mock

import pytest

from phishreport.io import command_plugins
from phishreport.io.check_command import CheckCommand
from phishreport.io.command_catalog import CommandCapabilities, discover_commands
from phishreport.io.command_plugins.help import create_command
from phishreport.io.commands import CommandRequest, CommandRouter
from phishreport.io.help_command import HelpCommand


@pytest.fixture
def capabilities():
    return CommandCapabilities(Mock(), Mock(), Mock(), Mock())


def test_help_factory_keeps_exact_catalog_and_does_not_call_services(capabilities):
    catalog = []
    context = CommandCapabilities(
        capabilities.prepare_record, capabilities.assess_record,
        capabilities.session_status, capabilities.report_count, catalog,
    )

    command = create_command(context)

    assert isinstance(command, HelpCommand)
    assert command.commands is catalog and context.commands is catalog
    assert catalog == []
    assert command.execute(CommandRequest("", "cli")).text == ""
    later = Mock()
    later.name, later.help_text = "later", "An appended command"
    catalog.append(later)
    first = command.execute(CommandRequest("", "cli"))
    second = command.execute(CommandRequest("ignored", "telegram"))
    assert first == second
    assert first.text == "/later: An appended command"
    assert catalog == [later]
    later.execute.assert_not_called()
    for service in (
        context.prepare_record, context.assess_record, context.session_status, context.report_count,
    ):
        service.assert_not_called()


def test_help_factory_uses_optional_empty_catalog_without_inserting_itself(capabilities):
    command = create_command(capabilities)

    assert command.commands is capabilities.commands
    assert command.execute(CommandRequest("", "cli")).text == ""
    assert capabilities.commands == ()


def test_actual_discovery_help_lists_itself_and_check_without_executing(capabilities, monkeypatch):
    check_execute = Mock(side_effect=AssertionError("Help executed Check"))
    monkeypatch.setattr(CheckCommand, "execute", check_execute)

    commands = discover_commands(capabilities)
    reply = CommandRouter(commands).route(CommandRequest("/help", "cli"))

    assert sum(command.name == "check" for command in commands) == 1
    assert sum(command.name == "help" for command in commands) == 1
    assert reply.kind == "help"
    assert reply.text.count("/help:") == 1
    assert f"/check: {CheckCommand.help_text}" in reply.text
    check_execute.assert_not_called()
    for service in (
        capabilities.prepare_record, capabilities.assess_record,
        capabilities.session_status, capabilities.report_count,
    ):
        service.assert_not_called()


def test_discovery_help_sees_later_drop_in_module(capabilities, tmp_path, monkeypatch):
    module_name = "phishreport.io.command_plugins.zz_help_factory_probe"
    attribute = module_name.rsplit(".", 1)[-1]
    assert module_name not in sys.modules and not hasattr(command_plugins, attribute)
    (tmp_path / f"{attribute}.py").write_text(
        "from phishreport.io.commands import Command, CommandReply\n"
        "class ProbeCommand(Command):\n"
        "    name = 'later_probe'\n"
        "    help_text = 'Discovered after Help'\n"
        "    def execute(self, request):\n"
        "        raise AssertionError('Help executed the probe')\n"
        "def create_command(capabilities):\n"
        "    return ProbeCommand()\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(command_plugins, "__path__", [*command_plugins.__path__, str(tmp_path)])
    importlib.invalidate_caches()
    try:
        commands = discover_commands(capabilities)
        help_command = next(command for command in commands if command.name == "help")
        probe_index = next(i for i, command in enumerate(commands) if command.name == "later_probe")
        assert commands.index(help_command) < probe_index
        assert help_command.commands is commands
        assert "/later_probe: Discovered after Help" in help_command.execute(
            CommandRequest("", "cli")
        ).text
    finally:
        sys.modules.pop(module_name, None)
        if hasattr(command_plugins, attribute):
            delattr(command_plugins, attribute)
        importlib.invalidate_caches()
