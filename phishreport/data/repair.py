"""Best-effort startup repair for histories with repeated assessments."""

from phishreport.errors import StorageFailure
from phishreport.logging_setup import AppLogging

from .manager import DataManager

logger = AppLogging.get_logger("data_repair")


class HistoryRepair:
    """Remove repeated assessment revisions from local history at startup."""

    @staticmethod
    def repair_history(manager: DataManager) -> int:
        """Remove duplicate assessment records and return how many were dropped.

        A malformed or unreadable history is left untouched rather than rewritten,
        and one fixed diagnostic is logged, so startup can continue. The repair is
        safe to run on every start: history without duplicates is not rewritten.
        """
        try:
            removed = manager.repair_duplicates()
        except StorageFailure:
            AppLogging.log_failure(
                logger,
                "Could not repair duplicate assessments; local history left unchanged.",
            )
            return 0
        if not isinstance(removed, int):
            return 0
        if removed:
            logger.warning(
                "Removed %d duplicate assessment record(s) from local history.", removed
            )
        return removed
