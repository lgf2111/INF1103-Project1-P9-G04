"""Immutable value describing the result produced by one priority rule."""

from dataclasses import dataclass

from .rule_trace import RuleTrace


@dataclass(frozen=True, slots=True)
class RuleOutcome:
    """Carry the winning rule's identity, score, and evaluation trace."""

    rule_name: str
    score: int
    trace: tuple[RuleTrace, ...] = ()
