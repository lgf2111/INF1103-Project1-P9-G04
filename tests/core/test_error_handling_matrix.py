"""Public service failures preserve private causes and recoverable local state."""

import sqlite3
from copy import deepcopy
from unittest.mock import Mock

import pytest

from phishreport.ai import AIManager, ProviderFailure, ProviderFailureReason
from phishreport.assessment import AssessmentService
from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
from phishreport.errors import AIUnavailable, FeedbackRejected, InvalidInput, StorageFailure
from phishreport.feedback import FeedbackService, FeedbackStore
from phishreport.logic import LogicManager
from phishreport.logic.validator import AssessmentValidationError

PRIVATE = "PRIVATE-token-and-message"
REPORT = {
    "schema_version": 2,
    "channel": "chat",
    "message": PRIVATE,
    "result": {"score": 10, "priority": "LOW", "reasons": [], "checklist": []},
}
CONTEXT = {
    "assessment_id": "assessment-matrix",
    "score": 10,
    "priority": "LOW",
    "reasons": ["Fictional assessment."],
}


def assert_safe(error, expected):
    assert type(error) is expected
    assert str(error) == error.user_message == expected.user_message
    assert PRIVATE not in str(error)
    assert PRIVATE not in repr(error)
    assert error.__cause__ is not None


@pytest.mark.parametrize("failure", ["provider", "input", "reply"])
def test_public_ai_failure_has_safe_message_without_mutating_input(failure):
    client = Mock()
    record = {"message": PRIVATE}
    expected = InvalidInput
    if failure == "provider":
        cause = ProviderFailure(ProviderFailureReason.TIMEOUT)
        cause.__cause__ = OSError(PRIVATE)
        client.complete.side_effect = cause
        expected = AIUnavailable
    elif failure == "input":
        record["sender"] = {"private": PRIVATE}
    else:
        client.complete.return_value = PRIVATE
    before = deepcopy(record)

    with pytest.raises(expected) as caught:
        AIManager(client=client).assess(record)

    assert_safe(caught.value, expected)
    assert record == before
    assert client.complete.call_count == (0 if failure == "input" else 1)
    if failure == "provider":
        assert caught.value.__cause__ is cause
        assert str(caught.value.__cause__.__cause__) == PRIVATE


@pytest.mark.parametrize("backend", ["json", "sqlite"])
@pytest.mark.parametrize("operation", ["read", "write"])
def test_public_history_failures_preserve_existing_file(
    tmp_path, monkeypatch, backend, operation,
):
    path = tmp_path / ("reports.json" if backend == "json" else "reports.sqlite3")
    storage = JsonReportStorage(path) if backend == "json" else SqliteReportStorage(path)
    manager = DataManager(storage=storage)
    manager.save(deepcopy(REPORT))
    if operation == "read":
        path.write_bytes(PRIVATE.encode())
    before = path.read_bytes()

    if operation == "write":
        if backend == "json":
            def fail_replace(*args):
                raise OSError(PRIVATE)

            monkeypatch.setattr("phishreport.data.json_storage.os.replace", fail_replace)
        else:
            original_connect = storage._connect

            def fail_write_connect(*, readonly=False):
                if not readonly:
                    raise sqlite3.OperationalError(PRIVATE)
                return original_connect(readonly=readonly)

            monkeypatch.setattr(storage, "_connect", fail_write_connect)

    with pytest.raises(StorageFailure) as caught:
        if operation == "read":
            manager.load(strict=True)
        else:
            manager.save(deepcopy(REPORT))

    assert_safe(caught.value, StorageFailure)
    assert path.read_bytes() == before
    assert not list(tmp_path.glob("*.tmp"))


def test_public_feedback_rejection_preserves_saved_feedback_and_context(tmp_path):
    path = tmp_path / "feedback.json"
    service = FeedbackService(FeedbackStore(path))
    service.submit(assessment_id=CONTEXT["assessment_id"], assessment_result=CONTEXT,
                   category="incorrect_explanation")
    before = path.read_bytes()
    context = deepcopy(CONTEXT)

    with pytest.raises(FeedbackRejected) as caught:
        service.submit(assessment_id=CONTEXT["assessment_id"], assessment_result=context,
                       category=PRIVATE, comment=PRIVATE)

    assert_safe(caught.value, FeedbackRejected)
    assert context == CONTEXT
    assert path.read_bytes() == before


def test_feedback_atomic_replace_failure_cleans_up_and_allows_one_retry(
    tmp_path, monkeypatch,
):
    path = tmp_path / "feedback.json"
    store = FeedbackStore(path)
    service = FeedbackService(store)
    arguments = {"assessment_id": CONTEXT["assessment_id"],
                 "assessment_result": deepcopy(CONTEXT), "category": "incorrect_explanation"}
    first = service.submit(**arguments)
    before = path.read_bytes()
    original_arguments = deepcopy(arguments)
    failure = OSError(PRIVATE)

    with monkeypatch.context() as patch:
        replace = Mock(side_effect=failure)
        patch.setattr("phishreport.feedback.store.os.replace", replace)
        with pytest.raises(StorageFailure) as caught:
            service.submit(**arguments)

        assert_safe(caught.value, StorageFailure)
        assert caught.value.__cause__ is failure
        replace.assert_called_once()
        assert path.read_bytes() == before
        assert store.load() == [first]
        assert sorted(item.name for item in tmp_path.iterdir()) == [path.name]

    retried = service.submit(**arguments)

    assert arguments == original_arguments
    assert retried.feedback_id != first.feedback_id
    assert store.load() == [first, retried]
    assert service.for_assessment(CONTEXT["assessment_id"]) == [first, retried]
    assert sorted(item.name for item in tmp_path.iterdir()) == [path.name]


def test_corrupt_feedback_read_preserves_file(tmp_path):
    path = tmp_path / "feedback.json"
    path.write_text(PRIVATE, encoding="utf-8")
    before = path.read_bytes()
    service = FeedbackService(FeedbackStore(path))

    with pytest.raises(StorageFailure) as caught:
        service.for_assessment(CONTEXT["assessment_id"])

    assert_safe(caught.value, StorageFailure)
    assert isinstance(caught.value.__cause__, ValueError)
    assert path.read_bytes() == before
    assert list(tmp_path.iterdir()) == [path]


@pytest.mark.parametrize("assessment_id", [None, "", "   ", 12])
def test_invalid_feedback_lookup_is_rejected_before_storage(assessment_id):
    store = Mock(spec=FeedbackStore)

    with pytest.raises(FeedbackRejected) as caught:
        FeedbackService(store).for_assessment(assessment_id)

    assert type(caught.value) is FeedbackRejected
    assert str(caught.value) == FeedbackRejected.user_message
    assert caught.value.__cause__ is None
    assert store.mock_calls == []


def test_invalid_new_report_is_rejected_before_any_storage_io():
    storage = Mock()
    report = {**deepcopy(REPORT), "message": None}
    before = deepcopy(report)

    with pytest.raises(InvalidInput) as caught:
        DataManager(storage=storage).save(report)

    assert_safe(caught.value, InvalidInput)
    assert isinstance(caught.value.__cause__, ValueError)
    assert report == before
    assert storage.mock_calls == []


@pytest.mark.parametrize("method", ["assess", "assess_with_findings", "rescore"])
@pytest.mark.parametrize("invalid", ["record", "findings"])
def test_real_logic_validation_has_typed_cause_without_mutating_inputs(method, invalid):
    record = {
        "channel": "chat", "sender": None, "message": PRIVATE,
        "has_link": False, "link": None, "has_file": False, "file_name": None,
        "clicked": False, "downloaded": False, "submitted_category": None,
    }
    findings = {"suspicious": False, "credential_request": False,
                "insufficient_context": False}
    if invalid == "record":
        record["clicked"] = PRIVATE
    else:
        findings["suspicious"] = PRIVATE
    before = deepcopy((record, findings))
    ai = Mock()
    ai.assess.return_value = findings
    service = AssessmentService(ai, LogicManager())

    with pytest.raises(InvalidInput) as caught:
        if method == "rescore":
            service.rescore(record, findings)
        else:
            getattr(service, method)(record)

    assert_safe(caught.value, InvalidInput)
    assert type(caught.value.__cause__) is AssessmentValidationError
    assert (record, findings) == before
    assert ai.assess.call_count == (0 if method == "rescore" else 1)
