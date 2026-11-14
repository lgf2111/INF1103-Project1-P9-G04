"""Bind session and saved-history status to transport-supplied readers."""

from phishreport.io.command_catalog import CommandCapabilities
from phishreport.io.status_command import StatusCommand


def create_command(capabilities: CommandCapabilities) -> StatusCommand:
    """Construct Status without invoking readers or changing the catalog."""
    return StatusCommand(
        session_status=capabilities.session_status,
        report_count=capabilities.report_count,
    )
