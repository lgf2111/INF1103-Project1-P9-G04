"""Read, filter and summarize persisted assessments through the same service."""

from unittest.mock import Mock

import pytest

from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
from phishreport.errors import StorageFailure
from phishreport.logic import LogicManager
from phishreport.reporting import ReportQueryService

LEGACY = {"channel": "SMS", "message": "First report", "score": 75, "priority": "high"}
CURRENT = {
    "schema_version": 3,
    "assessment_id": "saved-1",
    "channel": "sms",
    "message": "Last report",
    "result": {"score": 90, "priority": "HIGH", "reasons": [], "checklist": []},
}


@pytest.mark.parametrize("storage_type,suffix", [
    (JsonReportStorage, ".json"),
    (SqliteReportStorage, ".sqlite3"),
])
def test_query_preserves_order_and_uses_persisted_results(tmp_path, storage_type, suffix):
    storage = storage_type(tmp_path / ("reports" + suffix))
    records = [LEGACY, {"channel": "sms", "score": 80, "priority": "LOW"}, CURRENT]
    storage.write_records(records)
    logic = LogicManager()
    logic.evaluate = Mock(side_effect=AssertionError("History must use stored scores"))
    service = ReportQueryService(DataManager(storage), logic)

    selection = service.query(priority="high", channel="SMS", min_score=75)

    assert selection.records == [LEGACY, CURRENT]
    assert selection.history_count == 3
    assert selection.description == "priority High, channel SMS, score at least 75"
    assert service.summarize(selection).total == 2
    assert storage.read_records() == records
    logic.evaluate.assert_not_called()


def test_query_distinguishes_empty_history_no_matches_and_read_failure(tmp_path):
    destination = tmp_path / "history.json"
    storage = JsonReportStorage(destination)
    service = ReportQueryService(DataManager(storage), LogicManager())

    empty = service.query()
    assert empty.records == []
    assert empty.history_count == 0

    storage.write_records([LEGACY])
    no_matches = service.query(channel="email")
    assert no_matches.records == []
    assert no_matches.history_count == 1

    destination.write_text("invalid history", encoding="utf-8")
    with pytest.raises(StorageFailure):
        service.query()
    assert destination.read_text(encoding="utf-8") == "invalid history"


def test_query_filters_an_existing_snapshot_without_reloading(tmp_path):
    destination = tmp_path / "history.json"
    storage = JsonReportStorage(destination)
    storage.write_records([LEGACY])
    service = ReportQueryService(DataManager(storage), LogicManager())
    snapshot = service.load()

    storage.write_records([CURRENT])

    assert service.query(records=snapshot).records == [LEGACY]
    with pytest.raises(ValueError, match="Priority"):
        service.query(records=snapshot, priority="urgent")
