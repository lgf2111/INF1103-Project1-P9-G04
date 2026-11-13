"""Status reads injected capabilities without transport or assessment dependencies."""

from unittest.mock import Mock, call

import pytest

from phishreport.io.commands import CommandReply, CommandRequest, CommandRouter
from phishreport.io.status_command import StatusCommand


@pytest.mark.parametrize("count,status", [(0, "No active assessment"), (7, "2 awaiting answers")])
def test_status_reads_count_then_session_once_and_preserves_request(count, status):
    services = Mock()
    services.count.return_value = count
    services.status.return_value = status
    session = {"pending": "unchanged"}
    request = CommandRequest("ignored arguments", "telegram", session)

    reply = StatusCommand(services.status, services.count).execute(request)

    assert reply == CommandReply(f"Session: {status}\nSaved reports: {count}", "status")
    assert services.mock_calls == [call.count(), call.status(request)]
    forwarded = services.status.call_args.args[0]
    assert forwarded is request
    assert forwarded.channel == "telegram"
    assert forwarded.session is session
    assert session == {"pending": "unchanged"}


@pytest.mark.parametrize("error_type", [OSError, ValueError])
def test_status_count_failure_propagates_before_session_capability(error_type):
    error = error_type("History unavailable")
    count = Mock(side_effect=error)
    status = Mock()
    request = CommandRequest("", "cli", {"pending": "unchanged"})

    with pytest.raises(error_type) as caught:
        StatusCommand(status, count).execute(request)

    assert caught.value is error
    count.assert_called_once_with()
    status.assert_not_called()
    assert request.session == {"pending": "unchanged"}


def test_status_session_failure_propagates_without_changing_state():
    error = RuntimeError("Session unavailable")
    count = Mock(return_value=4)
    status = Mock(side_effect=error)
    request = CommandRequest("", "cli", {"existing": "preserved"})

    with pytest.raises(RuntimeError) as caught:
        StatusCommand(status, count).execute(request)

    assert caught.value is error
    count.assert_called_once_with()
    status.assert_called_once_with(request)
    assert request.session == {"existing": "preserved"}


def test_status_routes_with_arguments_without_using_them_as_session_state():
    status = Mock(return_value="No active assessment")
    count = Mock(return_value=3)
    command = StatusCommand(status, count)
    request = CommandRequest(" /status   ignored args ", "cli")

    reply = CommandRouter([command]).route(request)

    assert reply == CommandReply("Session: No active assessment\nSaved reports: 3", "status")
    forwarded = status.call_args.args[0]
    assert forwarded.text == "ignored args "
    assert forwarded.channel == "cli"
    assert forwarded.session is request.session
    assert command.name == "status" and command.help_text
