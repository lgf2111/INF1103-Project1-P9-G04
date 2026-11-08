"""Abstract contract implemented by each ordered scoring rule."""

from abc import ABC, abstractmethod


class PriorityRule(ABC):
    """Contract for one independently testable response-priority condition."""

    @abstractmethod
    def matches(self, record):
        """Return whether this rule applies to a validated record."""

    @abstractmethod
    def score(self, record):
        """Return this rule's response-priority score."""
