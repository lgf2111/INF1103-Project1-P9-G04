"""Per-assessment state for pending Telegram exposure answers."""

import asyncio
import secrets
import time
from copy import deepcopy

from phishreport.assessment import AssessmentSnapshot

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
