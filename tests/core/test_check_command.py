"""Offline behavior of the shared pasted-message assessment command."""

from unittest.mock import Mock

import pytest

from phishreport.assessment import AssessmentSnapshot
from phishreport.io.check_command import CheckCommand, CheckOutcome
from phishreport.io.commands import CommandReply, CommandRequest, CommandRouter


def test_check_preserves_input_and_assesses_once_before_publishing_outcome():
    record = {"channel": "chat", "message": "PAY Now\n  Example "}
    result = {"priority": "MEDIUM", "assessment_id": "stable-id"}
    session = {"existing": "preserved"}
    request = CommandRequest(record["message"], "telegram", session)
    prepare = Mock(return_value=record)
    assess = Mock(return_value=result)

    reply = CheckCommand(prepare, assess).execute(request)

    prepare.assert_called_once_with(request)
    assert prepare.call_args.args[0].session is session
    assess.assert_called_once_with(record)
    assert reply == CommandReply("Assessment ready.", "assessment")
    assert session["existing"] == "preserved"
    outcome = session["check_outcome"]
    assert isinstance(outcome, CheckOutcome)
    assert outcome.record == record
    assert outcome.result == result
    assert outcome.result["assessment_id"] == "stable-id"
    assert outcome.findings is None


def test_check_retains_findings_from_the_single_assessment_for_exposure_flow():
    record = {"message": "Parcel requires payment", "channel": "chat"}
    findings = {"suspicious": True, "details": ["Payment request"]}
    result = {"priority": "MEDIUM", "score": 60}
    assess = Mock(return_value=AssessmentSnapshot(findings, result))
    request = CommandRequest(record["message"], "telegram")

    CheckCommand(Mock(return_value=record), assess).execute(request)

    assess.assert_called_once_with(record)
    assert request.session["check_outcome"] == CheckOutcome(record, result, findings)


@pytest.mark.parametrize("text", ["", " ", "\n\t "])
def test_check_blank_input_returns_usage_without_calling_services(text):
    prepare = Mock()
    assess = Mock()
    request = CommandRequest(text, "cli", {"existing": "preserved"})

    reply = CheckCommand(prepare, assess).execute(request)

    assert reply.kind == "usage"
    assert "/check <text>" in reply.text
    prepare.assert_not_called()
    assess.assert_not_called()
    assert request.session == {"existing": "preserved"}


@pytest.mark.parametrize("failure_stage", ["prepare", "assess"])
def test_check_service_failure_propagates_without_replacing_previous_outcome(failure_stage):
    previous = object()
    request = CommandRequest("Message", "cli", {"check_outcome": previous})
    record = {"message": "Message"}
    prepare = Mock(return_value=record)
    assess = Mock(return_value={"priority": "MEDIUM"})
    error = ValueError("Invalid input or assessment")
    (prepare if failure_stage == "prepare" else assess).side_effect = error

    with pytest.raises(ValueError) as caught:
        CheckCommand(prepare, assess).execute(request)

    assert caught.value is error
    assert request.session == {"check_outcome": previous}
    prepare.assert_called_once_with(request)
    if failure_stage == "prepare":
        assess.assert_not_called()
    else:
        assess.assert_called_once_with(record)


def test_check_runs_as_a_command_through_the_existing_router():
    record = {"message": "URGENT  payment ", "channel": "chat"}
    prepare = Mock(return_value=record)
    assess = Mock(return_value={"priority": "MEDIUM"})
    command = CheckCommand(prepare, assess)
    request = CommandRequest(" /check   URGENT  payment ", "cli")

    reply = CommandRouter([command]).route(request)

    assert reply.kind == "assessment"
    forwarded = prepare.call_args.args[0]
    assert forwarded.text == "URGENT  payment "
    assert forwarded.channel == "cli"
    assert forwarded.session is request.session
    assert command.help_text
