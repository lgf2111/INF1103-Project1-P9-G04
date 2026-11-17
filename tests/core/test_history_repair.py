"""Report revisions replace their assessment instead of appending duplicates."""

import pytest

from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
from phishreport.data.repair import HistoryRepair

BACKENDS = {"json": JsonReportStorage, "sqlite": SqliteReportStorage}


def report(assessment_id, score):
    """Return a fictional v3 report for one revision of an assessment."""
    return {
        "schema_version": 3,
        "assessment_id": assessment_id,
        "channel": "chat",
        "message": f"Fictional message for {assessment_id} at {score}",
        "result": {
            "score": score,
            "priority": "HIGH" if score >= 80 else "MEDIUM",
            "reasons": [],
            "checklist": [],
        },
    }


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_saving_another_revision_replaces_the_same_assessment(tmp_path, backend):
    manager = DataManager(storage=BACKENDS[backend](tmp_path / "reports"))
    manager.save(report("assessment-a", 60))
    manager.save(report("assessment-b", 60))
    manager.save(report("assessment-a", 90))

    records = manager.load(strict=True)

    assert [record["assessment_id"] for record in records] == [
        "assessment-a",
        "assessment-b",
    ]
    assert records[0]["result"]["score"] == 90


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_repair_keeps_the_last_copy_of_a_repeated_assessment(tmp_path, backend):
    storage = BACKENDS[backend](tmp_path / "reports")
    legacy = {
        "channel": "email",
        "message": "Fictional older report",
        "score": 30,
        "priority": "LOW",
    }
    storage.write_records(
        [
            legacy,
            report("assessment-a", 60),
            report("assessment-b", 60),
            report("assessment-a", 80),
            report("assessment-a", 90),
        ]
    )

    manager = DataManager(storage=storage)
    assert manager.repair_duplicates() == 2

    records = manager.load(strict=True)
    assert [record.get("assessment_id") for record in records] == [
        None,
        "assessment-b",
        "assessment-a",
    ]
    assert records[2]["result"]["score"] == 90
    assert records[0] == legacy
    assert manager.repair_duplicates() == 0


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_repair_leaves_history_without_assessment_ids_untouched(tmp_path, backend):
    storage = BACKENDS[backend](tmp_path / "reports")
    records = [{"message": "one"}, {"message": "two"}]
    storage.write_records(records)

    assert storage.deduplicate_assessments() == 0
    assert storage.read_records() == records


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_repair_of_absent_history_creates_no_files(tmp_path, backend):
    assert BACKENDS[backend](tmp_path / "reports").deduplicate_assessments() == 0
    assert list(tmp_path.iterdir()) == []


def test_best_effort_startup_repair_preserves_unreadable_history(tmp_path):
    path = tmp_path / "reports.json"
    path.write_text("{broken", encoding="utf-8")

    assert HistoryRepair.repair_history(DataManager(JsonReportStorage(path))) == 0
    assert path.read_text(encoding="utf-8") == "{broken"
