"""Rule for reported clicks and downloads."""

from .base import PriorityRule


class ReportedInteractionRule(PriorityRule):
    """Apply caution for a click or download reported by the user."""

    def matches(self, record):
        return record["clicked"] or record["downloaded"]

    def score(self, record):
        return 35
