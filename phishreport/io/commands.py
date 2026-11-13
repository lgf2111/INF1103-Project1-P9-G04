"""Transport-independent command contracts and routing.

Transports supply a request and an explicit collection of commands. A None
reply means the input was not a registered command: the transport retains its
normal content handling. This module performs no terminal, API or storage I/O.
"""

import re
from abc import ABC, abstractmethod
from collections.abc import Iterable, MutableMapping
from dataclasses import dataclass, field, replace


@dataclass(frozen=True)
class CommandRequest:
    """Input text, transport channel and caller-owned mutable session state.

    Before routing, text is the complete user input. A recognized command
    receives only its argument text. The session is shared, not copied, so a
    command can update the caller's session without depending on a transport.
    """

    text: str
    channel: str
    session: MutableMapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CommandReply:
    """Text and a semantic kind interpreted by the calling transport."""

    text: str
    kind: str


class Command(ABC):
    """A single operation usable by any transport.

    Names are lowercase ASCII identifiers without the leading slash. Concrete
    commands own their services and error policy; the router does not convert
    service failures into a successful reply.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the command identifier, for example 'check'."""

    @property
    @abstractmethod
    def help_text(self) -> str:
        """Return a user-facing description of this command."""

    @abstractmethod
    def execute(self, request: CommandRequest) -> CommandReply:
        """Execute using argument text, channel and the caller's session."""


class CommandRouter:
    """Resolve an exact leading /name token against explicitly registered commands.

    Leading whitespace is ignored for recognition. Routing removes the command
    token and whitespace separating it from its arguments, preserving internal
    and trailing argument whitespace. Names are case-sensitive. Unknown slash
    tokens and ordinary content return None without executing any command or
    mutating the request. Registration never silently replaces a command.
    """

    def __init__(self, commands: Iterable[Command] = ()) -> None:
        self._commands: dict[str, Command] = {}
        for command in commands:
            self.register(command)

    def register(self, command: Command) -> None:
        """Register an implementation; reject invalid or duplicate names."""
        if not isinstance(command, Command):
            raise TypeError("Expected a Command implementation.")
        name = command.name
        if not isinstance(name, str) or re.fullmatch(r"[a-z][a-z0-9_]*", name) is None:
            raise ValueError("Command name must be a lowercase identifier without '/'.")
        if name in self._commands:
            raise ValueError(f"Command already registered: {name}")
        self._commands[name] = command

    def resolve(self, text: str) -> Command | None:
        """Look up a leading slash token without executing or changing input."""
        tokens = text.lstrip().split(maxsplit=1)
        if not tokens or not tokens[0].startswith("/"):
            return None
        return self._commands.get(tokens[0][1:])

    def route(self, request: CommandRequest) -> CommandReply | None:
        """Execute a recognized command, or leave input to the transport.

        Command exceptions propagate to the transport's error handler. A new
        request carries argument text while retaining the exact session object.
        """
        command = self.resolve(request.text)
        if command is None:
            return None
        text = request.text.lstrip()
        arguments = text[len(command.name) + 1:].lstrip()
        return command.execute(replace(request, text=arguments))
