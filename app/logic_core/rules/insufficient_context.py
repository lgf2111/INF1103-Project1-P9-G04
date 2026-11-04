"""Rule for limited AI assessment context."""

from .base import PriorityRule


class InsufficientContextRule(PriorityRule):
    """Reflect uncertainty when the AI reports insufficient context."""

    def matches(self, record):
        return record["ai"]["insufficient_context"]

    def score(self, record):
        return 20
