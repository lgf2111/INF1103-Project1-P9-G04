"""Evaluate ordered domain rules using their shared polymorphic contract."""

from .rules import (
    CredentialRequestRule,
    DefaultRule,
    DisclosureRule,
    InsufficientContextRule,
    ReportedInteractionRule,
    SuspiciousCredentialRule,
    SuspiciousInteractionRule,
    SuspiciousRule,
)


class PriorityRuleEngine:
    """Own and evaluate the ordered rule set used for assessment scoring."""

    def __init__(self, rules=None):
        self._rules = tuple(
            rules
            if rules is not None
            else (
                DisclosureRule(),
                SuspiciousInteractionRule(),
                SuspiciousCredentialRule(),
                SuspiciousRule(),
                CredentialRequestRule(),
                ReportedInteractionRule(),
                InsufficientContextRule(),
                DefaultRule(),
            )
        )

    def score(self, record):
        """Return the score from the first rule matching the validated record."""
        for rule in self._rules:
            if rule.matches(record):
                return rule.score(record)
        raise ValueError("Priority rules must include a fallback rule.")
