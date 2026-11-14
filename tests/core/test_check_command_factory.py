"""The discovered check factory binds existing capabilities without running them."""

from unittest.mock import Mock

import pytest

from phishreport.assessment import AssessmentSnapshot
from phishreport.io.check_command import CheckCommand
from phishreport.io.command_catalog import CommandCapabilities, discover_commands
from phishreport.io.command_plugins.check import create_command
from phishreport.io.commands import CommandRequest, CommandRouter


@pytest.fixture
def capabilities():
    return CommandCapabilities(Mock(), Mock(), Mock(), Mock())


def test_check_factory_binds_exact_services_without_calls_or_catalog_mutation(capabilities):
    catalog = [object()]
    context = CommandCapabilities(
        capabilities.prepare_record, capabilities.assess_record,
        capabilities.session_status, capabilities.report_count, catalog,
    )

    command = create_command(context)

    assert isinstance(command, CheckCommand)
    assert command.prepare_record is context.prepare_record
    assert command.assess_record is context.assess_record
    assert context.commands is catalog and len(catalog) == 1
    for service in (
        context.prepare_record, context.assess_record, context.session_status, context.report_count,
    ):
        service.assert_not_called()


@pytest.mark.parametrize("retain_findings", [False, True])
def test_real_discovery_routes_check_once_and_retains_result_and_findings(
    capabilities, retain_findings,
):
    commands = discover_commands(capabilities)
    checks = [command for command in commands if command.name == "check"]
    assert len(checks) == 1 and isinstance(checks[0], CheckCommand)
    capabilities.prepare_record.assert_not_called()
    capabilities.assess_record.assert_not_called()
    capabilities.session_status.assert_not_called()
    capabilities.report_count.assert_not_called()
    record = {"message": "Mixed CASE  message ", "channel": "chat"}
    findings = {"suspicious": True}
    result = {"score": 60, "priority": "MEDIUM", "assessment_id": "stable-id"}
    capabilities.prepare_record.return_value = record
    capabilities.assess_record.return_value = (
        AssessmentSnapshot(findings, result) if retain_findings else result
    )
    request = CommandRequest(" /check   Mixed CASE  message ", "telegram")

    reply = CommandRouter(commands).route(request)

    assert reply.kind == "assessment"
    forwarded = capabilities.prepare_record.call_args.args[0]
    assert forwarded.text == record["message"]
    assert forwarded.session is request.session
    capabilities.prepare_record.assert_called_once_with(forwarded)
    capabilities.assess_record.assert_called_once_with(record)
    outcome = request.session["check_outcome"]
    assert outcome.record is record and outcome.result is result
    assert outcome.result["assessment_id"] == "stable-id"
    assert outcome.findings is (findings if retain_findings else None)
    capabilities.session_status.assert_not_called()
    capabilities.report_count.assert_not_called()


def test_factory_check_empty_arguments_return_usage_without_services(capabilities):
    request = CommandRequest("/check  \t", "cli")

    reply = CommandRouter([create_command(capabilities)]).route(request)

    assert reply.kind == "usage" and "/check <text>" in reply.text
    capabilities.prepare_record.assert_not_called()
    capabilities.assess_record.assert_not_called()
    capabilities.session_status.assert_not_called()
    capabilities.report_count.assert_not_called()
    assert request.session == {}


def test_factory_check_service_failure_propagates_without_publishing(capabilities):
    failure = RuntimeError("Assessment unavailable")
    capabilities.prepare_record.return_value = {"message": "Message"}
    capabilities.assess_record.side_effect = failure
    request = CommandRequest("/check Message", "cli", {"existing": "preserved"})

    with pytest.raises(RuntimeError) as caught:
        CommandRouter([create_command(capabilities)]).route(request)

    assert caught.value is failure
    assert request.session == {"existing": "preserved"}
    capabilities.session_status.assert_not_called()
    capabilities.report_count.assert_not_called()
