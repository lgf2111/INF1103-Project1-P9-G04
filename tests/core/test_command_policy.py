"""Command metadata declares execution and failure policies without adapter coupling."""

import inspect
from dataclasses import FrozenInstanceError, fields
from unittest.mock import Mock

import pytest

from phishreport.io.check_command import CheckCommand
from phishreport.io.commands import (
    Command,
    CommandPolicy,
    CommandReply,
    CommandRequest,
    CommandRouter,
)
from phishreport.io.help_command import HelpCommand
from phishreport.io.status_command import StatusCommand


class OrdinaryCommand(Command):
    name = "ordinary"
    help_text = "A new ordinary command"

    def execute(self, request):
        return CommandReply(request.text, "text")


def test_new_command_inherits_immutable_reply_and_command_failure_defaults():
    command = OrdinaryCommand()

    assert command.policy == CommandPolicy(execution="reply", failure="command")
    with pytest.raises(FrozenInstanceError):
        command.policy.execution = "assessment"
    assert OrdinaryCommand().policy == CommandPolicy()


def test_builtin_commands_declare_behavior_without_adding_constructor_fields():
    check = CheckCommand(Mock(), Mock())
    status = StatusCommand(Mock(), Mock())
    help_command = HelpCommand([])

    assert check.policy == CommandPolicy(execution="assessment", failure="assessment")
    assert status.policy == CommandPolicy(execution="reply", failure="history")
    assert help_command.policy == CommandPolicy()
    for command in (check, status, help_command):
        assert "policy" not in inspect.signature(type(command)).parameters
        assert "policy" not in {field.name for field in fields(command)}


def test_router_keeps_declared_policy_and_executes_new_command_as_before():
    command = OrdinaryCommand()
    router = CommandRouter([command])
    request = CommandRequest("/ordinary Kept Case ", "cli")

    assert router.resolve(request.text) is command
    assert router.resolve(request.text).policy is command.policy
    assert router.route(request) == CommandReply("Kept Case ", "text")
    assert request.text == "/ordinary Kept Case " and request.session == {}


@pytest.mark.parametrize("error_type", [OSError, ValueError, RuntimeError, TypeError])
def test_router_leaves_error_handling_to_adapters_despite_policy(error_type):
    command = OrdinaryCommand()
    error = error_type("Command failed")
    command.execute = Mock(side_effect=error)

    with pytest.raises(error_type) as caught:
        CommandRouter([command]).route(CommandRequest("/ordinary", "cli"))

    assert caught.value is error
