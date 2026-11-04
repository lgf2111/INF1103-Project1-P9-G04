"""Highest-priority rule for user-reported credential disclosure."""

from .base import PriorityRule


class DisclosureRule(PriorityRule):
    """Prioritize a reported password or one-time-code disclosure."""

    def matches(self, record):
        return record["submitted_category"] in ("password", "otp")

    def score(self, record):
        return 90
