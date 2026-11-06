"""Terminal operations used by the CLI components."""

from typing import Protocol


class Terminal(Protocol):
    """Read answers and write lines through a replaceable terminal."""

    def read(self, prompt: str) -> str:
        """Prompt for an answer, propagating EOF and keyboard interruption."""
        ...

    def write(self, *parts: object) -> None:
        """Write parts separated by spaces and end with a newline."""
        ...
