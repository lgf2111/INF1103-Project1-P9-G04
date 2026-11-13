"""Abstract contract implemented by each ordered scoring rule."""

from abc import ABC, abstractmethod

from ..rule_outcome import RuleOutcome


class PriorityRule(ABC):
    """Contract for one independently testable response-priority condition."""

    def evaluate(self, record) -> RuleOutcome | None:
        """Return this rule's outcome when it matches, otherwise None."""
        if not self.matches(record):
            return None
        return RuleOutcome(rule_name=type(self).__name__, score=self.score(record))

    @abstractmethod
    def matches(self, record):
        """Return whether this rule applies to a validated record."""

    @abstractmethod
    def score(self, record):
        """Return this rule's response-priority score."""
