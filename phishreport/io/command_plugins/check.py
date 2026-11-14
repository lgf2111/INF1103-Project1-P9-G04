"""Bind pasted-message assessment to the capabilities supplied by a transport."""

from phishreport.io.check_command import CheckCommand
from phishreport.io.command_catalog import CommandCapabilities


def create_command(capabilities: CommandCapabilities) -> CheckCommand:
    """Construct the check command without executing any supplied service."""
    return CheckCommand(
        prepare_record=capabilities.prepare_record,
        assess_record=capabilities.assess_record,
    )
