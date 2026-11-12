"""Object-oriented domain logic for assessment scoring and guidance."""

from .manager import LogicManager
from .rule_outcome import RuleOutcome

__all__ = ["LogicManager", "RuleOutcome"]
