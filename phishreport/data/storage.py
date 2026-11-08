"""Storage contract independent of report schema and application policy."""

from abc import ABC, abstractmethod


class ReportStorage(ABC):
    """Replace ordered report dictionaries without validating their schema.

    Reads return fresh, independently mutable data, or [] for absent storage.
    Malformed stored contents raise ValueError; I/O errors raise OSError.
    Writes preserve values and order without mutating or retaining mutable
    caller data. Failures before replacement leave prior contents unchanged.
    Implementations propagate failures and do not print or recover silently.
    """

    @abstractmethod
    def read_records(self) -> list[dict]:
        """Return an independent snapshot of the complete stored list."""

    @abstractmethod
    def write_records(self, records: list[dict]) -> None:
        """Replace all records, preserving prior contents on pre-replace failure."""
