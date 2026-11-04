"""Rule for AI findings that mark content as suspicious."""

from .base import PriorityRule


class SuspiciousRule(PriorityRule):
    """Assign the standard suspicious-content score."""

    def matches(self, record):
        return record["ai"]["suspicious"]

    def score(self, record):
        return 45
