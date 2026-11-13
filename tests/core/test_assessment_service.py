"""The shared assessment workflow used by the CLI and the Telegram bot."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from phishreport.assessment import AssessmentService
from phishreport.logic import LogicManager

RECORD = {
    "channel": "chat",
    "sender": None,
    "message": "Your account is locked. Verify your password now.",
    "has_link": False,
    "link": None,
    "has_file": False,
    "file_name": None,
    "clicked": False,
    "downloaded": False,
    "submitted_category": None,
}
FINDINGS = {"suspicious": True, "credential_request": True, "insufficient_context": False}


def _service(findings=FINDINGS, error=None):
    ai_manager = Mock()
    if error is not None:
        ai_manager.assess.side_effect = error
    else:
        ai_manager.assess.return_value = findings
    return AssessmentService(ai_manager, LogicManager()), ai_manager


def test_assess_applies_the_business_rules_to_the_ai_findings():
    service, ai_manager = _service()

    result = service.assess(RECORD)

    assert (result["score"], result["priority"]) == (60, "MEDIUM")
    ai_manager.assess.assert_called_once_with(RECORD)


def test_assess_does_not_modify_the_input_record():
    service, _ = _service()
    before = dict(RECORD)

    service.assess(RECORD)

    assert RECORD == before
    assert "ai" not in RECORD


@pytest.mark.parametrize("error", [RuntimeError("timed out"), ValueError("bad reply")])
def test_assess_lets_ai_failures_reach_the_caller_without_a_fallback_outcome(error):
    service, _ = _service(error=error)

    with pytest.raises(type(error)):
        service.assess(RECORD)


def test_build_report_keeps_the_message_and_its_assessment():
    service, _ = _service()
    result = service.assess(RECORD)

    report = AssessmentService.build_report(RECORD, result)

    assert report == {
        "schema_version": 2,
        "channel": "chat",
        "message": RECORD["message"],
        "result": result,
    }


@pytest.mark.parametrize(
    ("clicked", "downloaded", "category", "answered"),
    [
        (None, None, None, False),
        (False, False, None, True),
        (True, None, None, False),
        (None, True, None, False),
        (False, True, "password", True),
        (True, False, "otp", True),
    ],
)
def test_build_exposure_report_preserves_exact_v3_shape_and_nullable_answers(
    clicked, downloaded, category, answered
):
    record = {**RECORD, "ai": FINDINGS, "extra": "discard"}
    result = {"score": 60, "priority": "MEDIUM", "reasons": [], "checklist": []}
    exposure = {
        "clicked": clicked,
        "downloaded": downloaded,
        "submitted_category": category,
        "disclosure_answered": answered,
        "ai": FINDINGS,
        "extra": "discard",
    }

    report = AssessmentService.build_exposure_report(record, result, exposure)

    assert report == {
        "schema_version": 3,
        "channel": "chat",
        "message": RECORD["message"],
        "result": result,
        "sender": None,
        "has_link": False,
        "link": None,
        "has_file": False,
        "file_name": None,
        "exposure": {
            "clicked": clicked,
            "downloaded": downloaded,
            "submitted_category": category,
            "disclosure_answered": answered,
        },
    }


@pytest.mark.parametrize("file_name", ["invoice.pdf", None])
def test_build_exposure_report_preserves_source_text_and_metadata(file_name):
    record = {
        **RECORD,
        "message": "  Open https://example.test/a?x=1\nAttachment mentioned.  ",
        "sender": "Original Sender",
        "has_link": True,
        "link": "https://example.test/a?x=1",
        "has_file": True,
        "file_name": file_name,
    }
    exposure = {
        "clicked": None,
        "downloaded": None,
        "submitted_category": None,
        "disclosure_answered": False,
    }

    report = AssessmentService.build_exposure_report(record, {}, exposure)

    for field in ("message", "sender", "has_link", "link", "has_file", "file_name"):
        assert report[field] == record[field]


def test_build_exposure_report_only_constructs_and_isolates_nested_inputs():
    # Deliberately unvalidated nested values exercise copying without introducing
    # schema/type validation, which belongs to ReportValidator.
    record = {**RECORD, "sender": {"labels": ["original"]}}
    result = {"reasons": [{"text": "urgent"}]}
    exposure = {
        "clicked": {"values": [True]},
        "downloaded": None,
        "submitted_category": None,
        "disclosure_answered": False,
    }
    before = deepcopy((record, result, exposure))
    ai_manager, logic_manager = Mock(), Mock()
    service = AssessmentService(ai_manager, logic_manager)

    report = service.build_exposure_report(record, result, exposure)

    assert (record, result, exposure) == before
    report["sender"]["labels"].append("report mutation")
    report["result"]["reasons"][0]["text"] = "report mutation"
    report["exposure"]["clicked"]["values"].append(False)
    assert (record, result, exposure) == before
    record["sender"]["labels"].append("input mutation")
    result["reasons"].append({"text": "input mutation"})
    exposure["clicked"]["values"].append(None)
    assert report["sender"]["labels"] == ["original", "report mutation"]
    assert report["result"]["reasons"] == [{"text": "report mutation"}]
    assert report["exposure"]["clicked"]["values"] == [True, False]
    ai_manager.assess.assert_not_called()
    logic_manager.evaluate.assert_not_called()


def test_assess_with_findings_retains_findings_and_scores_with_one_ai_call():
    service, ai_manager = _service()

    snapshot = service.assess_with_findings(RECORD)

    assert snapshot.findings == FINDINGS
    assert (snapshot.result["score"], snapshot.result["priority"]) == (60, "MEDIUM")
    ai_manager.assess.assert_called_once_with(RECORD)


def test_assess_with_findings_isolates_nested_findings_and_result():
    findings = {**FINDINGS, "details": {"clues": ["urgent"]}}
    result = {"score": 60, "priority": "MEDIUM", "reasons": [{"text": "urgent"}]}
    ai_manager = Mock()
    ai_manager.assess.return_value = findings
    logic_manager = Mock()
    logic_manager.evaluate.return_value = result
    service = AssessmentService(ai_manager, logic_manager)

    snapshot = service.assess_with_findings(RECORD)
    findings["details"]["clues"].append("external mutation")
    result["reasons"][0]["text"] = "external mutation"

    assert snapshot.findings["details"]["clues"] == ["urgent"]
    assert snapshot.result["reasons"] == [{"text": "urgent"}]
    snapshot.findings["details"]["clues"].append("snapshot mutation")
    snapshot.result["reasons"][0]["text"] = "snapshot mutation"
    assert findings["details"]["clues"] == ["urgent", "external mutation"]
    assert result["reasons"] == [{"text": "external mutation"}]


def test_assess_with_findings_protects_input_and_findings_from_collaborator_mutations():
    record = {**RECORD, "context": {"tags": ["original"]}}
    before = deepcopy(record)
    findings = {**FINDINGS, "details": {"clues": ["urgent"]}}
    ai_manager = Mock()

    def assess(working_record):
        working_record["context"]["tags"].append("AI mutation")
        return findings

    ai_manager.assess.side_effect = assess
    logic_manager = Mock()

    def evaluate(working_record):
        assert working_record["context"]["tags"] == ["original"]
        working_record["context"]["tags"].append("logic mutation")
        working_record["ai"]["details"]["clues"].append("logic mutation")
        return {"score": 60, "priority": "MEDIUM"}

    logic_manager.evaluate.side_effect = evaluate

    snapshot = AssessmentService(ai_manager, logic_manager).assess_with_findings(record)

    assert record == before
    assert snapshot.findings["details"]["clues"] == ["urgent"]
    assert findings["details"]["clues"] == ["urgent"]


def test_assess_with_findings_keeps_sequential_assessments_independent():
    service, ai_manager = _service()

    first = service.assess_with_findings(RECORD)
    second = service.assess_with_findings(RECORD)
    first.findings["suspicious"] = False
    first.result["reasons"].clear()

    assert second.findings == FINDINGS
    assert second.result["reasons"]
    assert ai_manager.assess.call_count == 2


@pytest.mark.parametrize("error", [RuntimeError("timed out"), ValueError("bad reply")])
def test_assess_with_findings_propagates_ai_errors_without_logic_or_input_mutation(error):
    record = {**RECORD, "context": {"tags": ["original"]}}
    before = deepcopy(record)
    ai_manager = Mock()

    def fail(working_record):
        working_record["context"]["tags"].clear()
        raise error

    ai_manager.assess.side_effect = fail
    logic_manager = Mock()
    service = AssessmentService(ai_manager, logic_manager)

    with pytest.raises(type(error)) as raised:
        service.assess_with_findings(record)

    assert raised.value is error
    assert record == before
    logic_manager.evaluate.assert_not_called()


def test_assess_with_findings_propagates_logic_errors_without_input_mutation():
    record = {**RECORD, "context": {"tags": ["original"]}}
    before = deepcopy(record)
    service, ai_manager = _service()
    error = ValueError("invalid record")
    logic_manager = Mock()

    def fail(working_record):
        working_record["context"]["tags"].clear()
        raise error

    logic_manager.evaluate.side_effect = fail
    service = AssessmentService(ai_manager, logic_manager)

    with pytest.raises(ValueError) as raised:
        service.assess_with_findings(record)

    assert raised.value is error
    assert record == before
    ai_manager.assess.assert_called_once_with(record)


@pytest.mark.parametrize(
    ("answers", "score", "priority"),
    [
        ({}, 60, "MEDIUM"),
        ({"clicked": True}, 80, "HIGH"),
        ({"downloaded": True}, 80, "HIGH"),
        ({"submitted_category": "password"}, 90, "HIGH"),
        ({"submitted_category": "otp"}, 90, "HIGH"),
    ],
)
def test_rescore_uses_explicit_findings_and_current_exposure_without_ai(
    answers, score, priority
):
    service, ai_manager = _service()
    record = {**RECORD, **answers, "ai": {**FINDINGS, "suspicious": False}}
    before = deepcopy(record)

    result = service.rescore(record, FINDINGS)

    assert (result["score"], result["priority"]) == (score, priority)
    assert record == before
    ai_manager.assess.assert_not_called()


def test_rescore_reuses_snapshot_across_answer_changes_with_only_one_ai_call():
    service, ai_manager = _service()
    snapshot = service.assess_with_findings(RECORD)
    before = deepcopy(snapshot)
    answers_and_scores = [
        ({"clicked": True}, 80),
        ({"downloaded": True}, 80),
        ({"submitted_category": "password"}, 90),
        ({"submitted_category": "otp"}, 90),
        ({}, 60),
    ]

    for answers, score in answers_and_scores:
        result = service.rescore({**RECORD, **answers}, snapshot.findings)
        assert result["score"] == score
        result["reasons"].clear()

    assert snapshot == before
    ai_manager.assess.assert_called_once_with(RECORD)


def test_rescore_isolates_inputs_and_result_from_mutating_logic():
    record = {**RECORD, "context": {"tags": ["original"]}}
    findings = {**FINDINGS, "details": {"clues": ["urgent"]}}
    record_before, findings_before = deepcopy(record), deepcopy(findings)
    ai_manager = Mock()
    logic_manager = Mock()
    collaborator_data = {}

    def evaluate(working_record):
        working_record["context"]["tags"].append("logic mutation")
        working_record["ai"]["details"]["clues"].append("logic mutation")
        collaborator_data.update(working_record)
        return collaborator_data

    logic_manager.evaluate.side_effect = evaluate
    service = AssessmentService(ai_manager, logic_manager)

    result = service.rescore(record, findings)
    collaborator_data["context"]["tags"].append("later mutation")
    result["ai"]["details"]["clues"].append("result mutation")

    assert result["context"]["tags"] == ["original", "logic mutation"]
    assert collaborator_data["ai"]["details"]["clues"] == ["urgent", "logic mutation"]
    assert record == record_before
    assert findings == findings_before
    ai_manager.assess.assert_not_called()


@pytest.mark.parametrize(
    ("record", "findings", "message"),
    [
        ({**RECORD, "clicked": "yes"}, FINDINGS, "clicked must be true or false"),
        ({**RECORD, "message": ""}, FINDINGS, "message must be non-empty text"),
        (RECORD, {**FINDINGS, "suspicious": "yes"}, "AI finding must be true or false"),
    ],
)
def test_rescore_propagates_validation_errors_without_ai(record, findings, message):
    service, ai_manager = _service()

    with pytest.raises(ValueError, match=message):
        service.rescore(record, findings)

    ai_manager.assess.assert_not_called()


@pytest.mark.parametrize("error", [ValueError("bad logic"), RuntimeError("failed logic")])
def test_rescore_propagates_logic_failure_without_ai_or_input_mutation(error):
    record = {**RECORD, "context": {"tags": ["original"]}}
    findings = {**FINDINGS, "details": {"clues": ["urgent"]}}
    record_before, findings_before = deepcopy(record), deepcopy(findings)
    ai_manager = Mock()
    logic_manager = Mock()

    def fail(working_record):
        working_record["context"]["tags"].clear()
        working_record["ai"]["details"]["clues"].clear()
        raise error

    logic_manager.evaluate.side_effect = fail
    service = AssessmentService(ai_manager, logic_manager)

    with pytest.raises(type(error)) as raised:
        service.rescore(record, findings)

    assert raised.value is error
    assert record == record_before
    assert findings == findings_before
    ai_manager.assess.assert_not_called()
