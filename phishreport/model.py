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


def _validate_result(result, *, allow_rule_trace=False):
    """Validate the score, priority, guidance and permitted explanation fields.

    Return None on success; raise ValueError without changing the result on
    failure. Four-field historical results remain valid. Newer v2 and v3
    reports may also carry the matched-rule trace. Empty guidance lists are
    accepted, but blank list entries are not.
    """
    required_fields = {
        "score",
        "priority",
        "reasons",
        "checklist",
    }
    optional_fields = {"matched_rule", "trace"} if allow_rule_trace else set()
    fields = set(result) if isinstance(result, dict) else set()
    if (
        not isinstance(result, dict)
        or not required_fields.issubset(fields)
        or not fields.issubset(required_fields | optional_fields)
        or (bool(fields.intersection(optional_fields)) and not optional_fields.issubset(fields))
    ):
        raise ValueError("Invalid stored assessment.")
    if type(result["score"]) is not int or not 0 <= result["score"] <= 100:
        raise ValueError("Invalid stored score.")
    if result["priority"] not in ("LOW", "MEDIUM", "HIGH"):
        raise ValueError("Invalid stored priority.")
    for key in ("reasons", "checklist"):
        values = result[key]
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError("Invalid stored text lists.")
    if optional_fields and optional_fields.issubset(fields):
        _validate_rule_trace(result)


def _validate_rule_trace(result):
    """Check that an optional trace ends at the recorded winning rule."""
    matched_rule = result["matched_rule"]
    trace = result["trace"]
    if not isinstance(matched_rule, str) or not matched_rule.strip():
        raise ValueError("Invalid matched rule.")
    if not isinstance(trace, list) or not trace:
        raise ValueError("Invalid stored rule trace.")
    trace_fields = {"rule_name", "matched", "score"}
    for step in trace:
        if not isinstance(step, dict) or set(step) != trace_fields:
            raise ValueError("Invalid stored rule trace step.")
        if not isinstance(step["rule_name"], str) or not step["rule_name"].strip():
            raise ValueError("Invalid stored rule name.")
        if type(step["matched"]) is not bool:
            raise ValueError("Invalid stored rule match flag.")
        score = step["score"]
        if step["matched"]:
            if type(score) is not int or not 0 <= score <= 100:
                raise ValueError("Invalid stored rule score.")
        elif score is not None:
            raise ValueError("Non-matching rules cannot have a score.")

    winning_step = trace[-1]
    if (
        any(step["matched"] for step in trace[:-1])
        or not winning_step["matched"]
        or winning_step["rule_name"] != matched_rule
        or winning_step["score"] != result["score"]
    ):
        raise ValueError("Stored rule trace does not match its assessment.")
