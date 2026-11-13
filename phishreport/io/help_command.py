"""Present help from a transport-independent command catalog."""

from collections.abc import Collection
from dataclasses import dataclass
from typing import ClassVar

from .commands import Command, CommandReply, CommandRequest


@dataclass
class HelpCommand(Command):
    """List the complete, uniquely named command catalog supplied by the caller.

    Catalog order is retained. Callers include this help command in that
    collection if they want it listed; no commands are inserted or executed.
    """

    commands: Collection[Command]

    name: ClassVar[str] = "help"
    help_text: ClassVar[str] = "List the available conversation commands"

    def execute(self, request: CommandRequest) -> CommandReply:
        """Return catalog help without changing the request or session."""
        return CommandReply(
            "\n".join(f"/{command.name}: {command.help_text}" for command in self.commands),
            "help",
        )
