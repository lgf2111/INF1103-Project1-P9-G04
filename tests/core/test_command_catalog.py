"""Discover real drop-in modules from the trusted internal command package."""

import importlib
import sys
from dataclasses import FrozenInstanceError
from unittest.mock import Mock

import pytest

from phishreport.io.command_catalog import CommandCapabilities, discover_commands
from phishreport.io.commands import CommandRequest


@pytest.fixture
def plugin_files(tmp_path, monkeypatch):
    from phishreport.io import command_plugins

    prefix = command_plugins.__name__ + "."
    original_modules = {name for name in sys.modules if name.startswith(prefix)}
    monkeypatch.setattr(command_plugins, "__path__", [str(tmp_path)])
    importlib.invalidate_caches()
    yield tmp_path
    for name in list(sys.modules):
        if name.startswith(prefix) and name not in original_modules:
            sys.modules.pop(name)
            attribute = name.removeprefix(prefix)
            if hasattr(command_plugins, attribute):
                delattr(command_plugins, attribute)
    importlib.invalidate_caches()


@pytest.fixture
def capabilities():
    return CommandCapabilities(Mock(), Mock(), Mock(), Mock())


def write_command(path, module, name):
    (path / f"{module}.py").write_text(
        "from phishreport.io.commands import Command, CommandReply\n"
        "class PluginCommand(Command):\n"
        f"    name = {name!r}\n"
        "    help_text = 'Drop-in command'\n"
        "    def execute(self, request):\n"
        "        return CommandReply('Executed', 'text')\n"
        "def create_command(capabilities):\n"
        "    return PluginCommand()\n",
        encoding="utf-8",
    )


def test_empty_package_discovers_nothing_and_does_not_call_capabilities(plugin_files, capabilities):
    assert discover_commands(capabilities) == []
    for service in (
        capabilities.prepare_record, capabilities.assess_record,
        capabilities.session_status, capabilities.report_count,
    ):
        service.assert_not_called()


def test_discovery_accepts_new_files_in_sorted_order_and_ignores_private_packages(
    plugin_files, capabilities,
):
    write_command(plugin_files, "zebra", "last")
    (plugin_files / "_private.py").write_text("raise AssertionError('Private imported')")
    package = plugin_files / "nested"
    package.mkdir()
    (package / "__init__.py").write_text("raise AssertionError('Package imported')")
    assert [command.name for command in discover_commands(capabilities)] == ["last"]
    write_command(plugin_files, "alpha", "first")
    importlib.invalidate_caches()

    commands = discover_commands(capabilities)

    assert [command.name for command in commands] == ["first", "last"]
    assert capabilities.commands == ()


def test_factory_gets_bound_capabilities_and_live_catalog_without_mutating_caller(
    plugin_files, capabilities,
):
    (plugin_files / "alpha.py").write_text(
        "from phishreport.io.help_command import HelpCommand\n"
        "received = None\n"
        "def create_command(capabilities):\n"
        "    global received\n"
        "    received = capabilities\n"
        "    return HelpCommand(capabilities.commands)\n",
        encoding="utf-8",
    )
    write_command(plugin_files, "zebra", "later")
    original_catalog = [object()]
    caller = CommandCapabilities(
        capabilities.prepare_record, capabilities.assess_record,
        capabilities.session_status, capabilities.report_count, original_catalog,
    )

    commands = discover_commands(caller)

    received = importlib.import_module("phishreport.io.command_plugins.alpha").received
    assert received is not caller
    assert received.prepare_record is caller.prepare_record
    assert received.assess_record is caller.assess_record
    assert received.session_status is caller.session_status
    assert received.report_count is caller.report_count
    assert received.commands is commands
    assert caller.commands is original_catalog and len(original_catalog) == 1
    reply = commands[0].execute(CommandRequest("", "test"))
    assert "/help:" in reply.text and "/later: Drop-in command" in reply.text
    with pytest.raises(FrozenInstanceError):
        caller.commands = []


@pytest.mark.parametrize("source", ["", "create_command = None", "create_command = 7"])
def test_missing_or_noncallable_factory_fails_explicitly(plugin_files, capabilities, source):
    (plugin_files / "broken.py").write_text(source, encoding="utf-8")

    with pytest.raises(TypeError, match="create_command"):
        discover_commands(capabilities)


def test_factory_return_must_implement_command(plugin_files, capabilities):
    (plugin_files / "broken.py").write_text(
        "def create_command(capabilities):\n    return object()\n", encoding="utf-8",
    )

    with pytest.raises(TypeError, match="Command"):
        discover_commands(capabilities)


def test_invalid_command_name_fails_registration(plugin_files, capabilities):
    write_command(plugin_files, "broken", "/invalid")

    with pytest.raises(ValueError, match="name"):
        discover_commands(capabilities)


def test_duplicate_names_fail_instead_of_replacing_commands(plugin_files, capabilities):
    write_command(plugin_files, "alpha", "same")
    write_command(plugin_files, "beta", "same")

    with pytest.raises(ValueError, match="already registered"):
        discover_commands(capabilities)


def test_factory_exception_propagates_unchanged_without_calling_services(
    plugin_files, capabilities,
):
    failure = RuntimeError("Factory failed")
    capabilities.report_count.side_effect = failure
    (plugin_files / "broken.py").write_text(
        "def create_command(capabilities):\n    raise capabilities.report_count.side_effect\n",
        encoding="utf-8",
    )

    with pytest.raises(RuntimeError) as caught:
        discover_commands(capabilities)

    assert caught.value is failure
    capabilities.report_count.assert_not_called()
    assert capabilities.commands == ()


def test_import_exception_is_not_hidden(plugin_files, capabilities):
    (plugin_files / "broken.py").write_text("raise ImportError('Plugin dependency missing')")

    with pytest.raises(ImportError, match="Plugin dependency missing"):
        discover_commands(capabilities)
