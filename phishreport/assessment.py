"""Shared assessment workflow used by every interface.

The CLI and the Telegram bot both turn an input record into an outcome the same
way: the AI Manager produces validated findings, and the Logic Manager applies
the business rules to the record enriched with those findings. Keeping the steps
here means both interfaces share one definition of an assessment.
"""

from copy import deepcopy
from dataclasses import dataclass


@dataclass
class AssessmentSnapshot:
    """Retained AI findings and the result of one assessment."""

    findings: dict
    result: dict


class AssessmentService:
    """Assess one record with the AI and Logic managers."""

    def __init__(self, ai_manager, logic_manager) -> None:
        self._ai_manager = ai_manager
        self._logic_manager = logic_manager

    def assess(self, record: dict) -> dict:
        """Return the evaluated outcome for a record.

        Raise RuntimeError if the AI service could not complete (offline, rate
        limited) and ValueError for invalid input or an invalid AI reply. The AI
        is never bypassed: the outcome is built only from validated findings.
        """
        findings = self._ai_manager.assess(record)
        # Enrich a new dictionary only after every AI check passes.
        return self._logic_manager.evaluate({**record, "ai": findings})

    def assess_with_findings(self, record: dict) -> AssessmentSnapshot:
        """Assess once and retain independent copies of findings and result.

        Collaborators receive working copies so their mutations cannot alter
        the caller's record or retained findings. AI and logic errors propagate
        to the caller without producing a snapshot.
        """
        findings = deepcopy(self._ai_manager.assess(deepcopy(record)))
        enriched_record = deepcopy(record)
        enriched_record["ai"] = deepcopy(findings)
        result = self._logic_manager.evaluate(enriched_record)
        return AssessmentSnapshot(findings=findings, result=deepcopy(result))

    @staticmethod
    def build_report(record: dict, result: dict) -> dict:
        """Return the version-2 report that keeps the message and its assessment."""
        return {
            "schema_version": 2,
            "channel": record["channel"],
            "message": record["message"],
            "result": result,
        }
