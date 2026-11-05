"""Compatibility interface for the class-based Logic Manager package.

The application currently imports this module-level interface. Domain logic
lives in ``logic_core``; these small adapters preserve existing callers while
the application can migrate to ``LogicManager`` independently.
"""

from logic_core import LogicManager

_DEFAULT_MANAGER = LogicManager()


def score(record):
    """Return a validated record's response-priority score."""
    return _DEFAULT_MANAGER.score(record)


def _priority(value):
    """Return the priority corresponding to a calculated score."""
    return _DEFAULT_MANAGER.priority_for(value)


def route(record):
    """Return a score and priority while preserving the historical patch point."""
    value = score(record)
    return {"score": value, "priority": _priority(value)}


def evaluate(record):
    """Return guidance while preserving the historical routing patch point."""
    outcome = route(record)
    return _DEFAULT_MANAGER.build_evaluation(record, outcome)


def _validate_record(record):
    """Validate required input fields without requiring AI findings."""
    _DEFAULT_MANAGER.validate_record(record)
