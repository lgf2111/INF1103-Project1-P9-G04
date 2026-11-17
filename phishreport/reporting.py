"""Query persisted assessment history independently of the CLI."""

from dataclasses import dataclass

from phishreport.data import DataManager
from phishreport.logic import LogicManager
from phishreport.logic.summary import ReportSummary


@dataclass(frozen=True)
class ReportQueryResult:
    """Ordered matching rows, filter description and original history size."""

    records: list[dict]
    description: str
    history_count: int


class ReportQueryService:
    """Read history strictly and filter or summarize stored outcomes."""

    def __init__(self, data_manager: DataManager, logic_manager: LogicManager) -> None:
        self._data_manager = data_manager
        self._logic_manager = logic_manager

    def load(self) -> list[dict]:
        """Load validated history, propagating storage failures to the caller."""
        return self._data_manager.load(strict=True)

    def query(
        self,
        *,
        priority: str | None = None,
        channel: str | None = None,
        min_score: int | None = None,
        records: list[dict] | None = None,
    ) -> ReportQueryResult:
        """Filter history in storage order, optionally using an already loaded snapshot."""
        if records is None:
            records = self.load()
        report_filter = self._logic_manager.build_filter(
            priority=priority, channel=channel, min_score=min_score,
        )
        return ReportQueryResult(
            records=[record for record in records if report_filter.matches(record)],
            description=report_filter.describe(),
            history_count=len(records),
        )

    def summarize(self, selection: ReportQueryResult) -> ReportSummary:
        """Summarize the selected persisted assessments."""
        return self._logic_manager.summarize(selection.records)
