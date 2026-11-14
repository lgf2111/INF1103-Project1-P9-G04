"""Discover trusted internal commands without transport-specific dependencies."""

import importlib
import pkgutil
from collections.abc import Callable, Collection
from dataclasses import dataclass, replace

from phishreport.assessment import AssessmentSnapshot

from . import command_plugins
from .commands import Command, CommandRequest, CommandRouter


@dataclass(frozen=True)
class CommandCapabilities:
    """Services injected into trusted factories, plus their live command catalog.

    Factories must not call services or mutate commands during discovery.
    Discovery provides a fresh catalog without changing the caller's context.
    """

    prepare_record: Callable[[CommandRequest], dict]
    assess_record: Callable[[dict], dict | AssessmentSnapshot]
    session_status: Callable[[CommandRequest], str]
    report_count: Callable[[], int]
    commands: Collection[Command] = ()


def discover_commands(capabilities: CommandCapabilities) -> list[Command]:
    """Build sorted public-module commands from the fixed internal package.

    Each immediate non-package module must expose create_command(capabilities).
    Import, factory and registration failures propagate; malformed extensions
    are never silently ignored. Trusted factory code owns its side effects.
    """
    catalog: list[Command] = []
    bound_capabilities = replace(capabilities, commands=catalog)
    router = CommandRouter()
    modules = sorted(pkgutil.iter_modules(command_plugins.__path__), key=lambda item: item.name)
    for module_info in modules:
        if module_info.ispkg or module_info.name.startswith("_"):
            continue
        module = importlib.import_module(f"{command_plugins.__name__}.{module_info.name}")
        factory = getattr(module, "create_command", None)
        if not callable(factory):
            raise TypeError(f"Command module {module.__name__} requires callable create_command.")
        command = factory(bound_capabilities)
        router.register(command)
        catalog.append(command)
    return catalog
