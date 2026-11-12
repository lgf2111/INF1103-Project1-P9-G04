"""Class-based orchestration for validation, scoring, routing, and guidance."""

from .priority_router import PriorityRouter
from .response_guidance import ResponseGuidanceBuilder
from .rule_engine import PriorityRuleEngine
from .validator import AssessmentValidator


class LogicManager:
    """Coordinate the domain logic collaborators for an AI-enriched record."""

    def __init__(self, validator=None, rule_engine=None, router=None, guidance_builder=None):
        self._validator = validator if validator is not None else AssessmentValidator()
        self._rule_engine = rule_engine if rule_engine is not None else PriorityRuleEngine()
        self._router = router if router is not None else PriorityRouter()
        self._guidance_builder = (
            guidance_builder if guidance_builder is not None else ResponseGuidanceBuilder()
        )

    def validate(self, record):
        """Validate the input record and the AI findings consumed by scoring."""
        self._validator.validate(record)

    def validate_record(self, record):
        """Validate the required input fields without requiring AI findings."""
        self._validator.validate_record(record)

    def score(self, record):
        """Validate and calculate the first matching response-priority score."""
        return self.rule_outcome(record).score

    def rule_outcome(self, record):
        """Validate a record and return its winning rule outcome value."""
        self.validate(record)
        return self._rule_engine.evaluate(record)

    def priority_for(self, score):
        """Return the priority label for a calculated score."""
        return self._router.priority_for(score)

    def route(self, record):
        """Return a score and its response-priority label."""
        score = self.score(record)
        return {"score": score, "priority": self.priority_for(score)}

    def evaluate(self, record):
        """Return score, priority, reasons, and exposure-aware response steps."""
        outcome = self.route(record)
        return self.build_evaluation(record, outcome)

    def build_evaluation(self, record, outcome):
        """Build evaluation guidance from an already calculated route outcome."""
        return self._guidance_builder.build(
            record, outcome["score"], outcome["priority"]
        )
