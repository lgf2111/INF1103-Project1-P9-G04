"""Coordinate report validation, history storage and read recovery."""

from collections.abc import Callable

from phishreport.logging_setup import AppLogging

from .json_storage import JsonReportStorage
from .storage import ReportStorage
from .validator import ReportValidator

logger = AppLogging.get_logger("data_manager")


class DataManager:
    """Manage reports through independently supplied storage and validation."""

    def __init__(
        self,
        storage: ReportStorage | None = None,
        validator: ReportValidator | None = None,
    ) -> None:
        self._storage = JsonReportStorage() if storage is None else storage
        self._validator = ReportValidator() if validator is None else validator

    def save(self, record: dict) -> None:
        """Append a new v2 or v3 report after validating the complete history.

        Validation and storage failures propagate without retrying. Storage
        replacement provides single-process semantics, not concurrent writes.
        """
        self._validator.validate_new(record)
        records = self.load(strict=True)
        self._storage.write_records([*records, record])

    def load(self, *, strict: bool = False) -> list[dict]:
        """Return complete validated history, or recover with [] by default.

        Strict callers receive the original read/validation error. Either mode
        logs one fixed diagnostic, with traceback detail only in debug mode.
        """
        try:
            records = self._storage.read_records()
            for record in records:
                self._validator.validate_stored(record)
            return records
        except (OSError, ValueError):
            AppLogging.log_failure(
                logger, "Could not read local report history; existing file preserved."
            )
            if strict:
                raise
            return []

    def query(self, filter_fn: Callable[[dict], bool]) -> list[dict]:
        """Filter tolerant history in order; propagate predicate exceptions."""
        return [record for record in self.load() if filter_fn(record)]
