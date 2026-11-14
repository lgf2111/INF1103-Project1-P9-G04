"""Report session state and saved-report count through injected capabilities."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from .commands import Command, CommandPolicy, CommandReply, CommandRequest


@dataclass
class StatusCommand(Command):
    """Read factual status without depending on a transport or storage backend."""

    session_status: Callable[[CommandRequest], str]
    report_count: Callable[[], int]

    name: ClassVar[str] = "status"
    help_text: ClassVar[str] = "Show session status and the number of saved reports"
    policy: ClassVar[CommandPolicy] = CommandPolicy(failure="history")

    def execute(self, request: CommandRequest) -> CommandReply:
        """Read history count before session status; propagate capability failures."""
        count = self.report_count()
        status = self.session_status(request)
        return CommandReply(f"Session: {status}\nSaved reports: {count}", "status")
