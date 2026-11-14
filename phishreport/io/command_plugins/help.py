"""Bind Help to the live command catalog supplied during discovery."""

from phishreport.io.command_catalog import CommandCapabilities
from phishreport.io.help_command import HelpCommand


def create_command(capabilities: CommandCapabilities) -> HelpCommand:
    """Construct Help without copying the catalog or executing services."""
    return HelpCommand(capabilities.commands)
