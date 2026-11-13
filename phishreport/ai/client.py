"""Contract for AI completion clients."""

from typing import Protocol


class AIClient(Protocol):
    """Complete a prompt without exposing provider-specific details."""

    def complete(self, prompt: str) -> str:
        """Return unchanged nonblank completion text for a nonblank prompt.

        Send the prompt unchanged. Raise ValueError for invalid input or
        RuntimeError for unavailable or invalid provider completions.
        """
        ...
