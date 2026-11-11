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
