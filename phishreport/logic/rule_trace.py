"""Immutable record of one rule check in the ordered scoring process."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RuleTrace:
    """Describe whether a rule matched and the score it produced, if any."""

    rule_name: str
    matched: bool
    score: int | None = None

    def as_dict(self) -> dict:
        """Return a JSON-compatible representation for interface adapters."""
        return {
            "rule_name": self.rule_name,
            "matched": self.matched,
            "score": self.score,
        }
