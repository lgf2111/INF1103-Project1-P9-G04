"""Evaluate ordered domain rules using their shared polymorphic contract."""

from .rule_outcome import RuleOutcome
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

    def evaluate(self, record) -> RuleOutcome:
        """Return the outcome from the first rule matching the validated record."""
        for rule in self._rules:
            outcome = rule.evaluate(record)
            if outcome is not None:
                return outcome
        raise ValueError("Priority rules must include a fallback rule.")

    def score(self, record):
        """Return the winning rule's numeric score for existing callers."""
        return self.evaluate(record).score
