"""Fallback rule when no higher-priority condition matches."""

from .base import PriorityRule


class DefaultRule(PriorityRule):
    """Provide the baseline response-priority score."""

    def matches(self, record):
        return True

    def score(self, record):
        return 10
