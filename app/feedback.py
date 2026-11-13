"""Value object for user feedback about one completed assessment."""

from dataclasses import dataclass
from datetime import datetime


FEEDBACK_CATEGORIES = frozenset(
    {
        "false_positive",
        "false_negative",
        "incorrect_priority",
        "incorrect_explanation",
        "application_bug",
        "usability_issue",
        "other",
    }
)
PRIORITIES = frozenset({"LOW", "MEDIUM", "HIGH"})
FEEDBACK_FIELDS = {
    "feedback_id",
    "assessment_id",
    "category",
    "comment",
    "corrected_priority",
    "assessment_score",
    "assessment_priority",
    "assessment_reasons",
    "matched_rule",
    "created_at",
}


@dataclass(frozen=True, slots=True)
class Feedback:
    """An immutable correction record with the assessment context needed to review it."""

    feedback_id: str
    assessment_id: str
    category: str
    comment: str | None
    corrected_priority: str | None
    assessment_score: int
    assessment_priority: str
    assessment_reasons: tuple[str, ...]
    matched_rule: str | None
    created_at: str

    def __post_init__(self):
        """Reject invalid feedback before it can enter the local store."""
        for name, value in (("feedback_id", self.feedback_id), ("assessment_id", self.assessment_id)):
            if not isinstance(value, str) or not value.strip() or len(value) > 100:
                raise ValueError("Invalid feedback identifier: " + name)
        if not isinstance(self.category, str) or self.category not in FEEDBACK_CATEGORIES:
            raise ValueError("Unsupported feedback category.")
        if self.comment is not None and (
            not isinstance(self.comment, str) or len(self.comment) > 2000
        ):
            raise ValueError("Feedback comment must be text of at most 2000 characters.")
        if self.corrected_priority is not None and (
            not isinstance(self.corrected_priority, str)
            or self.corrected_priority not in PRIORITIES
        ):
            raise ValueError("Invalid corrected priority.")
        if type(self.assessment_score) is not int or not 0 <= self.assessment_score <= 100:
            raise ValueError("Invalid assessment score in feedback context.")
        if (
            not isinstance(self.assessment_priority, str)
            or self.assessment_priority not in PRIORITIES
        ):
            raise ValueError("Invalid assessment priority in feedback context.")
        if not isinstance(self.assessment_reasons, tuple) or any(
            not isinstance(reason, str) or not reason.strip()
            for reason in self.assessment_reasons
        ):
            raise ValueError("Invalid assessment reasons in feedback context.")
        if self.matched_rule is not None and not isinstance(self.matched_rule, str):
            raise ValueError("Invalid matched rule in feedback context.")
        if not isinstance(self.created_at, str):
            raise ValueError("Invalid feedback timestamp.")
        try:
            timestamp = datetime.fromisoformat(self.created_at.replace("Z", "+00:00"))
        except ValueError as error:
            raise ValueError("Invalid feedback timestamp.") from error
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("Feedback timestamp must include a timezone.")

    def to_dict(self) -> dict:
        """Return the stable JSON representation used by FeedbackStore."""
        return {
            "feedback_id": self.feedback_id,
            "assessment_id": self.assessment_id,
            "category": self.category,
            "comment": self.comment,
            "corrected_priority": self.corrected_priority,
            "assessment_score": self.assessment_score,
            "assessment_priority": self.assessment_priority,
            "assessment_reasons": list(self.assessment_reasons),
            "matched_rule": self.matched_rule,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, record: dict):
        """Build a validated value object from one stored JSON object."""
        if not isinstance(record, dict) or set(record) != FEEDBACK_FIELDS:
            raise ValueError("Stored feedback has an invalid shape.")
        reasons = record["assessment_reasons"]
        if not isinstance(reasons, list):
            raise ValueError("Stored assessment reasons must be a list.")
        return cls(
            feedback_id=record["feedback_id"],
            assessment_id=record["assessment_id"],
            category=record["category"],
            comment=record["comment"],
            corrected_priority=record["corrected_priority"],
            assessment_score=record["assessment_score"],
            assessment_priority=record["assessment_priority"],
            assessment_reasons=tuple(reasons),
            matched_rule=record["matched_rule"],
            created_at=record["created_at"],
        )
