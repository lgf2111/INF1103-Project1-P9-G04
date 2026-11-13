"""Application workflow for submitting and retrieving assessment feedback."""

from datetime import datetime, timezone
from uuid import uuid4

from .feedback import Feedback
from .store import FeedbackStore


class FeedbackService:
    """Convert user corrections and assessment context into stored feedback."""

    def __init__(self, store: FeedbackStore) -> None:
        self._store = store

    def submit(
        self,
        *,
        assessment_id: str,
        assessment_result: dict,
        category: str,
        comment: str | None = None,
        corrected_priority: str | None = None,
    ) -> Feedback:
        """Persist a correction linked to an assessment snapshot."""
        if not isinstance(assessment_result, dict):
            raise ValueError("Assessment context must be an object.")
        if assessment_result.get("assessment_id") != assessment_id:
            raise ValueError("Feedback assessment identifier does not match its context.")
        required = {"score", "priority", "reasons"}
        if not required.issubset(assessment_result):
            raise ValueError("Assessment context is missing score, priority or reasons.")
        reasons = assessment_result["reasons"]
        if not isinstance(reasons, (list, tuple)):
            raise ValueError("Assessment reasons must be a list.")

        feedback = Feedback(
            feedback_id=str(uuid4()),
            assessment_id=assessment_id,
            category=category,
            comment=comment,
            corrected_priority=corrected_priority,
            assessment_score=assessment_result["score"],
            assessment_priority=assessment_result["priority"],
            assessment_reasons=tuple(reasons),
            matched_rule=assessment_result.get("matched_rule"),
            created_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        )
        self._store.add(feedback)
        return feedback

    def for_assessment(self, assessment_id: str) -> list[Feedback]:
        """Return feedback associated with a saved assessment identifier."""
        return self._store.for_assessment(assessment_id)
