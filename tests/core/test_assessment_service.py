"""The shared assessment workflow used by the CLI and the Telegram bot."""

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
