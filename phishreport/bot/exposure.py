"""Per-assessment state for pending Telegram exposure answers."""

import asyncio
import secrets
import time
from copy import deepcopy

from phishreport.assessment import AssessmentService, AssessmentSnapshot

SESSION_TIMEOUT_SECONDS = 30 * 60


class ExposureSession:
    """Keep one user's pending assessment and lifecycle state independent."""

    def __init__(
        self,
        record: dict,
        snapshot: AssessmentSnapshot,
        *,
        chat_id: int,
        user_id: int,
        message_id: int,
    ) -> None:
        self.record = deepcopy(record)
        self.findings = deepcopy(snapshot.findings)
        self.result = deepcopy(snapshot.result)
        self.exposure = {
            "clicked": None,
            "downloaded": None,
            "submitted_category": None,
            "disclosure_answered": False,
        }
        self.chat_id = chat_id
        self.user_id = user_id
        self.message_id = message_id
        self.reply_message_id = None
        self.token = secrets.token_urlsafe(12)
        self.created_at = time.monotonic()
        self.expires_at = self.created_at + SESSION_TIMEOUT_SECONDS
        self.completed = False
        self.saved = False
        self.report = None
        self.lock = asyncio.Lock()

    def apply_answer(self, action: str, assessment: AssessmentService) -> dict:
        """Apply one answer and re-score retained findings without I/O.

        Async callback callers must serialize this operation with self.lock.
        Rejected answers and scoring/copy failures leave the session unchanged.
        Return a result independent of both stored and collaborator payloads.
        """
        interaction_answers = {
            "clicked": (True, False),
            "downloaded": (False, True),
            "both": (True, True),
            "neither": (False, False),
        }
        if not isinstance(action, str) or action not in (
            *interaction_answers, "password", "otp", "no_disclosure"
        ):
            raise ValueError("Unknown exposure answer")
        if self.completed or self.saved:
            raise ValueError("Exposure session is already completed or saved")
        if time.monotonic() >= self.expires_at:
            raise ValueError("Exposure session has expired")

        candidate = deepcopy(self.exposure)
        if action in interaction_answers:
            candidate["clicked"], candidate["downloaded"] = interaction_answers[action]
        else:
            candidate["submitted_category"] = None if action == "no_disclosure" else action
            candidate["disclosure_answered"] = True

        record = deepcopy(self.record)
        record["clicked"] = candidate["clicked"] is True
        record["downloaded"] = candidate["downloaded"] is True
        record["submitted_category"] = (
            candidate["submitted_category"]
            if candidate["disclosure_answered"] is True else None
        )
        result = deepcopy(assessment.rescore(record, deepcopy(self.findings)))
        returned_result = deepcopy(result)
        self.exposure = candidate
        self.result = result
        return returned_result

    def complete(self, assessment: AssessmentService) -> dict:
        """Freeze the current answers/result into a v3 report without I/O.

        Async callback callers must serialize this operation with self.lock.
        Stage independent report/return copies before changing lifecycle state;
        failures leave the session unchanged. Replays return the cached report
        even after expiry, supporting later storage retries without re-scoring.
        Completion alone does not mark the report as saved.
        """
        if self.completed:
            return deepcopy(self.report)
        if time.monotonic() >= self.expires_at:
            raise ValueError("Exposure session has expired")

        report = deepcopy(assessment.build_exposure_report(
            deepcopy(self.record), deepcopy(self.result), deepcopy(self.exposure)
        ))
        returned_report = deepcopy(report)
        self.report = report
        self.completed = True
        return returned_report
