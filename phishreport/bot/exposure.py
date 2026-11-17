"""Per-assessment state for an exposure card that is saved as soon as it is shown."""

import asyncio
import secrets
import time
from copy import deepcopy
from uuid import uuid4

from phishreport.assessment import AssessmentService, AssessmentSnapshot

SESSION_TIMEOUT_SECONDS = 30 * 60
ANSWER_ACTIONS = {"clicked", "password"}


class ExposureSession:
    """Keep one saved assessment and the follow-up answers it still accepts."""

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
        self.assessment_id = str(uuid4())
        self.chat_id = chat_id
        self.user_id = user_id
        self.message_id = message_id
        self.reply_message_id = None
        self.token = secrets.token_urlsafe(12)
        self.created_at = time.monotonic()
        self.expires_at = self.created_at + SESSION_TIMEOUT_SECONDS
        self.report = None
        self.saved = False
        self.dismissed = False
        self.lock = asyncio.Lock()

    @property
    def answered(self) -> bool:
        """Whether at least one follow-up answer is already part of the result."""
        return (
            self.exposure["clicked"] is True
            or self.exposure["disclosure_answered"] is True
        )

    def build_report(
        self,
        assessment: AssessmentService,
        *,
        exposure: dict | None = None,
        result: dict | None = None,
    ) -> dict:
        """Build one v3 revision with this session's stable assessment identifier.

        Use the supplied candidate answers and result, or the retained state.
        Inputs and the returned report are independent copies; nothing changes.
        """
        return assessment.build_exposure_report(
            deepcopy(self.record),
            deepcopy(self.result if result is None else result),
            deepcopy(self.exposure if exposure is None else exposure),
            assessment_id=self.assessment_id,
        )

    def answer(self, action: str, assessment: AssessmentService) -> tuple[dict, dict] | None:
        """Return candidate answers and a re-scored result without I/O.

        Async callers must serialize this with self.lock and persist the matching
        report before committing the candidate. Return None when the answer is
        already recorded. Unknown, dismissed or late answers raise ValueError
        and change nothing; retained findings keep the AI out of this path.
        """
        if not isinstance(action, str) or action not in ANSWER_ACTIONS:
            raise ValueError("Unknown exposure answer")
        if self.dismissed:
            raise ValueError("Exposure session is dismissed")
        if time.monotonic() >= self.expires_at:
            raise ValueError("Exposure session has expired")

        candidate = deepcopy(self.exposure)
        if action == "clicked":
            candidate["clicked"] = True
        else:
            candidate["submitted_category"] = "password"
            candidate["disclosure_answered"] = True
        if candidate == self.exposure:
            return None

        record = deepcopy(self.record)
        record["clicked"] = candidate["clicked"] is True
        record["downloaded"] = candidate["downloaded"] is True
        record["submitted_category"] = (
            candidate["submitted_category"]
            if candidate["disclosure_answered"] is True else None
        )
        result = deepcopy(assessment.rescore(record, deepcopy(self.findings)))
        return candidate, result

    def commit(self, exposure: dict, result: dict, report: dict) -> None:
        """Adopt one revision only after its write succeeded."""
        self.exposure = deepcopy(exposure)
        self.result = deepcopy(result)
        self.report = deepcopy(report)
        self.saved = True

    def dismiss(self) -> None:
        """Stop offering answers while leaving the saved report untouched."""
        self.dismissed = True
