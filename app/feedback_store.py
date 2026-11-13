"""Local persistence for assessment feedback, separate from report history."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from feedback import Feedback


class FeedbackStore:
    """Validate and persist feedback records in an independent JSON file.

    The store is intended for the current single-process CLI and future shared
    application service. Concurrent writers are not supported.
    """

    def __init__(self, path="feedback.json"):
        self._path = Path(path)

    def submit(
        self,
        *,
        assessment_id: str,
        assessment_result: dict,
        category: str,
        comment: str | None = None,
        corrected_priority: str | None = None,
    ) -> Feedback:
        """Validate and persist feedback linked to an assessment snapshot."""
        if not isinstance(assessment_result, dict):
            raise ValueError("Assessment context must be an object.")
        required = {"score", "priority", "reasons"}
        if not required.issubset(assessment_result):
            raise ValueError("Assessment context is missing score, priority or reasons.")
        reasons = assessment_result["reasons"]
        if not isinstance(reasons, list):
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
        records = self.load()
        if any(item.feedback_id == feedback.feedback_id for item in records):
            raise ValueError("Duplicate feedback identifier.")
        records.append(feedback)
        self._write(records)
        return feedback

    def load(self) -> list[Feedback]:
        """Return all feedback in submission order, rejecting corrupt history."""
        try:
            with self._path.open(encoding="utf-8") as stream:
                records = json.load(
                    stream,
                    object_pairs_hook=self._unique_fields,
                    parse_constant=self._invalid_constant,
                )
        except FileNotFoundError:
            return []
        except (json.JSONDecodeError, UnicodeError, RecursionError) as error:
            raise ValueError("Feedback history is malformed; existing file preserved.") from error

        if not isinstance(records, list):
            raise ValueError("Feedback history must be a list.")
        feedback = [Feedback.from_dict(record) for record in records]
        identifiers = [item.feedback_id for item in feedback]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("Feedback history contains duplicate identifiers.")
        return feedback

    def for_assessment(self, assessment_id: str) -> list[Feedback]:
        """Return feedback for one assessment, preserving submission order."""
        if not isinstance(assessment_id, str) or not assessment_id.strip():
            raise ValueError("Assessment identifier must be non-empty text.")
        return [item for item in self.load() if item.assessment_id == assessment_id]

    @staticmethod
    def _unique_fields(pairs):
        """Reject duplicate JSON keys rather than silently discarding feedback."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Feedback history contains duplicate fields.")
            result[key] = value
        return result

    @staticmethod
    def _invalid_constant(value):
        """Reject NaN and infinity, which are outside standard JSON."""
        raise ValueError("Feedback history contains a non-JSON constant: " + value)

    def _write(self, records: list[Feedback]) -> None:
        """Atomically replace the feedback list after validating all records."""
        serialized = [item.to_dict() for item in records]
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self._path.parent,
                suffix=".tmp",
                delete=False,
            ) as stream:
                temporary = stream.name
                json.dump(serialized, stream, indent=2, ensure_ascii=False, allow_nan=False)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self._path)
        finally:
            if temporary is not None and os.path.exists(temporary):
                os.unlink(temporary)
