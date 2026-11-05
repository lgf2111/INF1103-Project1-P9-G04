"""Compatibility functions for local report storage through DataManager."""

from collections.abc import Callable

from data_core import DataManager, JsonReportStorage

FILE = "reports.json"


def save(record: dict) -> None:
    """Append a version-2 report using the current FILE setting.

    Validation and storage failures propagate; existing history is preserved
    on failures before replacement. Concurrent writers are not supported.
    """
    DataManager(storage=JsonReportStorage(FILE)).save(record)


def load(*, strict: bool = False) -> list[dict]:
    """Load validated history, recovering with [] unless strict is requested."""
    return DataManager(storage=JsonReportStorage(FILE)).load(strict=strict)


def query(filter_fn: Callable[[dict], bool]) -> list[dict]:
    """Filter current history in stored order using tolerant read recovery."""
    return DataManager(storage=JsonReportStorage(FILE)).query(filter_fn)
