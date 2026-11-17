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
        """Save one report revision, replacing the copy with the same assessment_id.

        Validation and storage failures become domain errors without retrying. The
        write itself is one protected storage operation, so concurrent processes
        do not discard each other's reports and a repeated exposure tap cannot
        append a second copy of the same assessment.
        """
        try:
            self._validator.validate_new(record)
        except ValueError as error:
            raise InvalidInput() from error
        self.load(strict=True)  # Reject unreadable or invalid history first.
        try:
            self._storage.save(record)
        except (OSError, ValueError) as error:
            raise StorageFailure() from error

    def repair_duplicates(self) -> int:
        """Remove repeated assessment revisions, keeping each last copy.

        Records without an assessment_id are left alone, and the storage layer
        applies the removal as one protected read-modify-write.
        """
        try:
            return self._storage.deduplicate_assessments()
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
