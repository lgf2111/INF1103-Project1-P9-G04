"""Immutable value describing the result produced by one priority rule."""

from dataclasses import dataclass

from .rule_trace import RuleTrace


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """Carry the winning rule's identity and score as one value."""

    rule_name: str
    score: int
    trace: tuple[RuleTrace, ...] = ()
