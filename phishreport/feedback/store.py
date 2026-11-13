"""Local JSON persistence for feedback, separate from assessment reports."""

import json
import os
import tempfile
from pathlib import Path

from .feedback import Feedback


class FeedbackStore:
    """Persist validated feedback records without storing message bodies."""

    def __init__(self, path: str | os.PathLike[str] = "feedback.json") -> None:
        self._path = Path(path)

    def add(self, feedback: Feedback) -> None:
        """Append one validated feedback record and atomically replace the file."""
        if not isinstance(feedback, Feedback):
            raise TypeError("FeedbackStore accepts Feedback records.")
        records = self.load()
        if any(item.feedback_id == feedback.feedback_id for item in records):
            raise ValueError("Duplicate feedback identifier.")
        records.append(feedback)
        self._write(records)

    def load(self) -> list[Feedback]:
        """Load feedback in submission order; reject malformed history safely."""
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
        """Return feedback for one assessment in original submission order."""
        if not isinstance(assessment_id, str) or not assessment_id.strip():
            raise ValueError("Assessment identifier must be non-empty text.")
        return [item for item in self.load() if item.assessment_id == assessment_id]

    @staticmethod
    def _unique_fields(pairs) -> dict:
        """Reject duplicate JSON keys rather than silently discarding values."""
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Feedback history contains duplicate fields.")
            result[key] = value
        return result

    @staticmethod
    def _invalid_constant(value: str):
        """Reject non-standard JSON numbers such as NaN and infinity."""
        raise ValueError("Feedback history contains a non-JSON constant: " + value)

    def _write(self, feedback: list[Feedback]) -> None:
        """Atomically replace the JSON file after serializing validated records."""
        serialized = [item.to_dict() for item in feedback]
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
