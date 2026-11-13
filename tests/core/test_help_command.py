"""Help uses the supplied command catalog without executing its commands."""

from unittest.mock import Mock

from phishreport.io.commands import CommandReply, CommandRequest, CommandRouter
from phishreport.io.help_command import HelpCommand


def test_help_lists_catalog_metadata_in_supplied_order_without_execution():
    check = Mock(name="check command")
    check.name = "check"
    check.help_text = "Assess a pasted message"
    status = Mock(name="status command")
    status.name = "status"
    status.help_text = "Show the session and report count"
    request = CommandRequest("ignored arguments", "cli", {"session": "existing"})

    reply = HelpCommand([status, check]).execute(request)

    assert reply == CommandReply(
        "/status: Show the session and report count\n/check: Assess a pasted message",
        "help",
    )
    status.execute.assert_not_called()
    check.execute.assert_not_called()
    assert request.text == "ignored arguments"
    assert request.channel == "cli"
    assert request.session == {"session": "existing"}


def test_help_empty_catalog_returns_empty_text_without_inserting_itself():
    assert HelpCommand([]).execute(CommandRequest("", "telegram")) == CommandReply(
        "", "help"
    )


def test_help_repeated_calls_do_not_change_catalog_or_session():
    catalog = []
    command = HelpCommand(catalog)
    catalog.append(command)
    session = {"pending": object()}
    request = CommandRequest("any arguments", "telegram", session)
    before = session.copy()

    first = command.execute(request)
    second = command.execute(request)

    assert first == second == CommandReply(f"/help: {command.help_text}", "help")
    assert catalog == [command]
    assert session == before
    assert request.session is session


def test_help_routes_through_the_existing_router():
    catalog = []
    command = HelpCommand(catalog)
    catalog.append(command)
    router = CommandRouter(catalog)
    request = CommandRequest(" /help  ignored ", "cli")

    assert router.route(request) == CommandReply(f"/help: {command.help_text}", "help")
    assert request.text == " /help  ignored "
    assert request.session == {}
