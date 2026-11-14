"""The discovered Status factory binds factual readers without running them."""

from unittest.mock import Mock, call

import pytest

from phishreport.io.command_catalog import CommandCapabilities, discover_commands
from phishreport.io.command_plugins.status import create_command
from phishreport.io.commands import CommandReply, CommandRequest, CommandRouter
from phishreport.io.status_command import StatusCommand


@pytest.fixture
def capabilities():
    return CommandCapabilities(Mock(), Mock(), Mock(), Mock())


def test_status_factory_binds_exact_readers_without_calls_or_catalog_mutation(capabilities):
    catalog = [object()]
    context = CommandCapabilities(
        capabilities.prepare_record, capabilities.assess_record,
        capabilities.session_status, capabilities.report_count, catalog,
    )

    command = create_command(context)

    assert isinstance(command, StatusCommand)
    assert command.session_status is context.session_status
    assert command.report_count is context.report_count
    assert context.commands is catalog and len(catalog) == 1
    for service in (
        context.prepare_record, context.assess_record, context.session_status, context.report_count,
    ):
        service.assert_not_called()


@pytest.mark.parametrize("count,status", [
    (0, "No pending assessment"), (3, "One awaiting answers"),
])
def test_discovered_status_reads_count_then_session_once_with_original_context(count, status):
    services = Mock()
    services.count.return_value = count
    services.status.return_value = status
    capabilities = CommandCapabilities(Mock(), Mock(), services.status, services.count)
    commands = discover_commands(capabilities)
    assert sum(command.name == "status" for command in commands) == 1
    assert services.mock_calls == []
    session = {"pending": "retained"}
    request = CommandRequest(" /status ignored ", "telegram", session)

    reply = CommandRouter(commands).route(request)

    assert reply == CommandReply(f"Session: {status}\nSaved reports: {count}", "status")
    forwarded = services.status.call_args.args[0]
    assert forwarded.channel == request.channel and forwarded.session is session
    assert forwarded.text == "ignored "
    assert services.mock_calls == [call.count(), call.status(forwarded)]
    assert session == {"pending": "retained"}
    capabilities.prepare_record.assert_not_called()
    capabilities.assess_record.assert_not_called()


@pytest.mark.parametrize("stage", ["count", "status"])
def test_factory_status_reader_failures_propagate_without_fallback_or_state_change(
    capabilities, stage,
):
    failure = (
        OSError("History unavailable") if stage == "count" else ValueError("Status unavailable")
    )
    capabilities.report_count.return_value = 4
    capabilities.session_status.return_value = "Pending"
    reader = capabilities.report_count if stage == "count" else capabilities.session_status
    reader.side_effect = failure
    request = CommandRequest("ignored", "cli", {"existing": "preserved"})

    with pytest.raises(type(failure)) as caught:
        create_command(capabilities).execute(request)

    assert caught.value is failure
    capabilities.report_count.assert_called_once_with()
    if stage == "count":
        capabilities.session_status.assert_not_called()
    else:
        capabilities.session_status.assert_called_once_with(request)
    assert request.session == {"existing": "preserved"}
    capabilities.prepare_record.assert_not_called()
    capabilities.assess_record.assert_not_called()


def test_discovered_help_sees_status_loaded_after_it_without_executing_services(capabilities):
    commands = discover_commands(capabilities)
    help_command = next(command for command in commands if command.name == "help")
    status_command = next(command for command in commands if command.name == "status")

    reply = CommandRouter(commands).route(CommandRequest("/help", "cli"))

    assert commands.index(help_command) < commands.index(status_command)
    assert help_command.commands is commands
    assert reply.text.count(f"/status: {StatusCommand.help_text}") == 1
    for service in (
        capabilities.prepare_record, capabilities.assess_record,
        capabilities.session_status, capabilities.report_count,
    ):
        service.assert_not_called()
