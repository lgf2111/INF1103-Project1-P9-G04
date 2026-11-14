"""Startup derives Telegram menu entries from real discovered command modules."""

import asyncio
import importlib
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import pytest
from telegram.error import TelegramError
from telegram.ext import Application

from phishreport.io import command_plugins
from phishreport.io.check_command import CheckCommand
from phishreport.io.help_command import HelpCommand
from phishreport.io.status_command import StatusCommand


@pytest.fixture
def plugin_files(tmp_path, monkeypatch):
    prefix = command_plugins.__name__ + "."
    original_modules = {name for name in sys.modules if name.startswith(prefix)}
    monkeypatch.setattr(command_plugins, "__path__", [*command_plugins.__path__, str(tmp_path)])

    def write(module="zz_menu_probe", name="menu_probe", description="A discovered command"):
        (tmp_path / f"{module}.py").write_text(
            "from phishreport.io.commands import Command\n"
            "class MenuCommand(Command):\n"
            f"    name = {name!r}\n"
            f"    help_text = {description!r}\n"
            "    def execute(self, request):\n"
            "        raise AssertionError('Metadata must not execute commands')\n"
            "def create_command(capabilities):\n"
            "    return MenuCommand()\n",
            encoding="utf-8",
        )
        importlib.invalidate_caches()

    yield tmp_path, write
    for name in list(sys.modules):
        if name.startswith(prefix) and name not in original_modules:
            sys.modules.pop(name)
            attribute = name.removeprefix(prefix)
            if hasattr(command_plugins, attribute):
                delattr(command_plugins, attribute)
    importlib.invalidate_caches()


@pytest.fixture
def menu_startup(tmp_path, monkeypatch):
    module = importlib.import_module("phishreport.bot.main")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:offline-token")
    monkeypatch.delenv("TELEGRAM_ALLOWED_CHAT_ID", raising=False)
    monkeypatch.setenv("PHISHREPORT_GMAIL_PATH", str(tmp_path / "gmail.json"))
    monkeypatch.setattr(module.AppLogging, "setup", lambda: True)
    data = Mock()
    assessment = Mock()
    builder = Mock()
    monkeypatch.setattr(module, "DataManager", Mock(return_value=data))
    monkeypatch.setattr(module, "AssessmentService", Mock(return_value=assessment))
    monkeypatch.setattr(module, "AIManager", Mock())
    monkeypatch.setattr(module, "create_report_storage", Mock())
    monkeypatch.setattr(module, "ChatRecordBuilder", Mock(return_value=builder), raising=False)
    monitor = Mock(run=AsyncMock())
    monitor_factory = Mock(return_value=monitor)
    monkeypatch.setattr(module, "EmailMonitor", monitor_factory)
    with patch.object(Application, "run_polling", autospec=True) as polling:
        assert module.main() == 0
    app, = polling.call_args.args
    fake_app = SimpleNamespace(
        bot=SimpleNamespace(set_my_commands=AsyncMock(), username="offline_bot"), bot_data={},
    )
    return module, app, fake_app, monitor_factory, monitor, data, assessment, builder


def test_startup_discovers_drop_in_metadata_without_executing_services(plugin_files, menu_startup):
    path, write = plugin_files
    write()
    module, app, fake_app, monitor_factory, monitor, data, assessment, builder = menu_startup

    async def scenario():
        await app.post_init(fake_app)
        await fake_app.bot_data["monitor_task"]

    asyncio.run(scenario())

    entries = fake_app.bot.set_my_commands.await_args.args[0]
    names = [entry.command for entry in entries]
    assert names[:4] == ["start", "linkgmail", "checkmail", "unlinkgmail"]
    assert names[4:] == ["check", "help", "status", "menu_probe"]
    metadata = {entry.command: entry.description for entry in entries}
    assert metadata[CheckCommand.name] == CheckCommand.help_text
    assert metadata[HelpCommand.name] == HelpCommand.help_text
    assert metadata[StatusCommand.name] == StatusCommand.help_text
    assert metadata["menu_probe"] == "A discovered command"
    assert [entry.command for entry in module.COMMANDS] == names[:4]
    monitor_factory.assert_called_once()
    monitor.run.assert_awaited_once()
    data.load.assert_not_called()
    data.save.assert_not_called()
    assessment.assess_with_findings.assert_not_called()
    builder.build.assert_not_called()


@pytest.mark.parametrize("name", ["start", "linkgmail"])
def test_native_name_collision_fails_before_menu_or_monitor(plugin_files, menu_startup, name):
    path, write = plugin_files
    write(name=name)
    module, app, fake_app, monitor_factory, monitor, data, assessment, builder = menu_startup

    with pytest.raises(ValueError, match="command"):
        asyncio.run(app.post_init(fake_app))

    fake_app.bot.set_my_commands.assert_not_awaited()
    monitor_factory.assert_not_called()
    assert not fake_app.bot_data


@pytest.mark.parametrize("name,description,valid", [
    ("x" * 32, "d" * 256, True),
    ("x" * 33, "Description", False),
    ("valid", "", False),
    ("valid", "d" * 257, False),
    ("valid", None, False),
])
def test_telegram_metadata_limits_are_enforced_at_startup(
    plugin_files, menu_startup, name, description, valid,
):
    path, write = plugin_files
    write(name=name, description=description)
    module, app, fake_app, monitor_factory, monitor, data, assessment, builder = menu_startup

    async def scenario():
        if valid:
            await app.post_init(fake_app)
            await fake_app.bot_data["monitor_task"]
        else:
            with pytest.raises(ValueError):
                await app.post_init(fake_app)

    asyncio.run(scenario())

    if valid:
        fake_app.bot.set_my_commands.assert_awaited_once()
    else:
        fake_app.bot.set_my_commands.assert_not_awaited()
        monitor_factory.assert_not_called()
        assert not fake_app.bot_data


@pytest.mark.parametrize("extra,total,valid", [(93, 100, True), (94, 101, False)])
def test_telegram_total_command_limit_before_api(plugin_files, menu_startup, extra, total, valid):
    path, write = plugin_files
    for number in range(extra):
        write(module=f"zz_menu_{number:03}", name=f"menu_{number}")
    module, app, fake_app, monitor_factory, monitor, data, assessment, builder = menu_startup

    async def scenario():
        if valid:
            await app.post_init(fake_app)
            await fake_app.bot_data["monitor_task"]
        else:
            with pytest.raises(ValueError):
                await app.post_init(fake_app)

    asyncio.run(scenario())

    if valid:
        assert len(fake_app.bot.set_my_commands.await_args.args[0]) == total
    else:
        fake_app.bot.set_my_commands.assert_not_awaited()
        monitor_factory.assert_not_called()


def test_factory_error_propagates_before_menu_and_monitor(plugin_files, menu_startup):
    path, write = plugin_files
    (path / "zz_menu_broken.py").write_text(
        "FAILURE = ValueError('Factory unavailable')\n"
        "def create_command(capabilities):\n    raise FAILURE\n",
        encoding="utf-8",
    )
    importlib.invalidate_caches()
    broken = importlib.import_module("phishreport.io.command_plugins.zz_menu_broken")
    module, app, fake_app, monitor_factory, monitor, data, assessment, builder = menu_startup

    with pytest.raises(ValueError) as caught:
        asyncio.run(app.post_init(fake_app))

    assert caught.value is broken.FAILURE
    fake_app.bot.set_my_commands.assert_not_awaited()
    monitor_factory.assert_not_called()
    assert not fake_app.bot_data


def test_menu_api_failure_does_not_start_monitor(menu_startup):
    module, app, fake_app, monitor_factory, monitor, data, assessment, builder = menu_startup
    failure = TelegramError("Menu unavailable")
    fake_app.bot.set_my_commands.side_effect = failure

    with pytest.raises(TelegramError) as caught:
        asyncio.run(app.post_init(fake_app))

    assert caught.value is failure
    monitor_factory.assert_not_called()
    assert not fake_app.bot_data


def test_plugin_import_failure_precedes_api_and_monitor(plugin_files, menu_startup):
    path, write = plugin_files
    (path / "zz_menu_import_failure.py").write_text(
        "raise ImportError('Missing plugin dependency')\n", encoding="utf-8",
    )
    importlib.invalidate_caches()
    module, app, fake_app, monitor_factory, monitor, data, assessment, builder = menu_startup

    with pytest.raises(ImportError, match="Missing plugin dependency"):
        asyncio.run(app.post_init(fake_app))

    fake_app.bot.set_my_commands.assert_not_awaited()
    monitor_factory.assert_not_called()
    assert not fake_app.bot_data


def test_successful_menu_startup_retains_monitor_shutdown_cleanup(menu_startup):
    module, app, fake_app, monitor_factory, monitor, data, assessment, builder = menu_startup

    async def scenario():
        started = asyncio.Event()

        async def run():
            started.set()
            await asyncio.Event().wait()

        monitor.run.side_effect = run
        await app.post_init(fake_app)
        await asyncio.wait_for(started.wait(), 1)
        assert fake_app.bot_data["monitor"] is monitor
        task = fake_app.bot_data["monitor_task"]
        await app.post_shutdown(fake_app)
        with pytest.raises(asyncio.CancelledError):
            await task
        assert task.done()

    asyncio.run(scenario())

    fake_app.bot.set_my_commands.assert_awaited_once()
    monitor_factory.assert_called_once()
    monitor.run.assert_awaited_once()
