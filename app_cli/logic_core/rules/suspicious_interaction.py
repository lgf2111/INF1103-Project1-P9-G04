"""Rule for suspicious messages with a reported interaction."""

from .base import PriorityRule


class SuspiciousInteractionRule(PriorityRule):
    """Raise priority when a suspicious message was clicked or downloaded."""

    def matches(self, record):
        findings = record["ai"]
        return findings["suspicious"] and (record["clicked"] or record["downloaded"])

    def score(self, record):
        return 80
