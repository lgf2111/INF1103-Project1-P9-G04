"""Shared report contract foundations independent of storage and transports."""

from collections.abc import Mapping
from types import MappingProxyType

SCHEMA_VERSION = 3
SCHEMA_VERSION_KEY = "schema_version"


def _freeze_json(value: object) -> object:
    """Own an acyclic JSON-shaped value through recursively read-only containers.

    Copy mapping contents into read-only mappings and sequences into tuples.
    Preserve scalar values exactly; report-field validation belongs to the model
    contracts added separately. Never include rejected input in error messages.
    """
    error_message = "Report data must use JSON-compatible values and string object keys."
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(error_message)
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise ValueError(error_message)
