"""Shared assessment workflow used by every interface.

The CLI and the Telegram bot both turn an input record into an outcome the same
way: the AI Manager produces validated findings, and the Logic Manager applies
the business rules to the record enriched with those findings. Keeping the steps
here means both interfaces share one definition of an assessment.
"""

from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4


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
        result = self._logic_manager.evaluate({**record, "ai": findings})
        return {**result, "assessment_id": str(uuid4())}

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

    def rescore(self, record: dict, findings: dict) -> dict:
        """Evaluate current exposure with retained findings and no AI call.

        Explicit findings replace any record findings. Working inputs and the
        returned result are independent copies; logic errors propagate unchanged.
        """
        enriched_record = deepcopy(record)
        enriched_record["ai"] = deepcopy(findings)
        return deepcopy(self._logic_manager.evaluate(enriched_record))

    @staticmethod
    def build_report(record: dict, result: dict) -> dict:
        """Return a version-3 report with a stable identifier for feedback links."""
        assessment_id = result.get("assessment_id")
        if not isinstance(assessment_id, str) or not assessment_id.strip():
            raise ValueError("Assessment result is missing its identifier.")
        saved_result = {key: value for key, value in result.items() if key != "assessment_id"}
        return {
            "schema_version": 3,
            "assessment_id": assessment_id,
            "channel": record["channel"],
            "message": record["message"],
            "result": saved_result,
        }

    @staticmethod
    def build_exposure_report(record: dict, result: dict, exposure: dict) -> dict:
        """Construct an independent v3 report preserving explicit exposure answers.

        Select only report fields without scoring or validation. Unknown answers
        remain None; disclosure_answered distinguishes unknown from confirmed no.
        """
        return deepcopy(
            {
                "schema_version": 3,
                "assessment_id": str(uuid4()),
                "channel": record["channel"],
                "message": record["message"],
                "result": result,
                "sender": record["sender"],
                "has_link": record["has_link"],
                "link": record["link"],
                "has_file": record["has_file"],
                "file_name": record["file_name"],
                "exposure": {
                    "clicked": exposure["clicked"],
                    "downloaded": exposure["downloaded"],
                    "submitted_category": exposure["submitted_category"],
                    "disclosure_answered": exposure["disclosure_answered"],
                },
            }
        )
