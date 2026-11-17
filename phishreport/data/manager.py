"""Coordinate report validation, history storage and read recovery."""

from collections.abc import Callable

from phishreport.errors import InvalidInput, StorageFailure
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

        Validation and storage failures become domain errors without retrying. The
        append itself is one protected storage operation, so concurrent processes
        do not discard each other's reports.
        """
        try:
            self._validator.validate_new(record)
        except ValueError as error:
            raise InvalidInput() from error
        records = self.load(strict=True)  # Reject unreadable or invalid history first.
        try:
            if type(self._storage).append is ReportStorage.append:
                # Storage without its own atomic append: read-then-write, single process only.
                self._storage.write_records([*records, record])
            else:
                self._storage.append(record)
        except (OSError, ValueError) as error:
            raise StorageFailure() from error

    def load(self, *, strict: bool = False) -> list[dict]:
        """Return complete validated history, or recover with [] by default.

        Strict callers receive StorageFailure chained from the original error.
        Either mode logs one fixed diagnostic, with traceback detail only in
        debug mode.
        """
        try:
            records = self._storage.read_records()
            for record in records:
                self._validator.validate_stored(record)
            return records
        except (OSError, ValueError) as error:
            AppLogging.log_failure(
                logger, "Could not read local report history; existing file preserved."
            )
            if strict:
                raise StorageFailure() from error
            return []

    def query(self, filter_fn: Callable[[dict], bool]) -> list[dict]:
        """Filter tolerant history in order; propagate predicate exceptions."""
        return [record for record in self.load() if filter_fn(record)]
