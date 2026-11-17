"""Shared assessment workflow used by every interface.

The CLI and the Telegram bot both turn an input record into an outcome the same
way: the AI Manager produces validated findings, and the Logic Manager applies
the business rules to the record enriched with those findings. Keeping the steps
here means both interfaces share one definition of an assessment.
"""

from copy import deepcopy
from dataclasses import dataclass
from uuid import uuid4

from phishreport.errors import InvalidInput
from phishreport.logic.validator import AssessmentValidationError
from phishreport.model import Report


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

        Raise AIUnavailable for known AI service failures and InvalidInput for
        invalid records or AI replies. Unexpected collaborator errors propagate
        unchanged. The outcome is built only from validated findings.
        """
        findings = self._ai_manager.assess(record)
        # Enrich a new dictionary only after every AI check passes.
        try:
            result = self._logic_manager.evaluate({**record, "ai": findings})
        except AssessmentValidationError as error:
            raise InvalidInput() from error
        return {**result, "assessment_id": str(uuid4())}

    def assess_with_findings(self, record: dict) -> AssessmentSnapshot:
        """Assess once and retain independent copies of findings and result.

        Collaborators receive working copies so their mutations cannot alter
        the caller's record or retained findings. AI and logic errors propagate
        to the caller without producing a snapshot. Known record/findings
        validation failures become InvalidInput; other logic errors propagate.
        """
        findings = deepcopy(self._ai_manager.assess(deepcopy(record)))
        enriched_record = deepcopy(record)
        enriched_record["ai"] = deepcopy(findings)
        try:
            result = self._logic_manager.evaluate(enriched_record)
        except AssessmentValidationError as error:
            raise InvalidInput() from error
        return AssessmentSnapshot(findings=findings, result=deepcopy(result))

    def rescore(self, record: dict, findings: dict) -> dict:
        """Evaluate current exposure with retained findings and no AI call.

        Explicit findings replace any record findings. Working inputs and the
        returned result are independent copies. Known record/findings validation
        failures become InvalidInput; other logic errors propagate unchanged.
        """
        enriched_record = deepcopy(record)
        enriched_record["ai"] = deepcopy(findings)
        try:
            result = self._logic_manager.evaluate(enriched_record)
        except AssessmentValidationError as error:
            raise InvalidInput() from error
        return deepcopy(result)

    @staticmethod
    def build_report(record: dict, result: dict) -> dict:
        """Return a version-3 report with a stable identifier for feedback links."""
        return Report.from_assessment(record, result).to_dict()

    @staticmethod
    def build_exposure_report(
        record: dict, result: dict, exposure: dict, assessment_id: str | None = None,
    ) -> dict:
        """Validate and serialize an independent v3 report with a stable identifier.

        Use the supplied identifier, or generate a fresh one. Select only report
        fields without scoring or reassessment. Unknown answers remain None;
        disclosure_answered distinguishes unknown from confirmed no.
        """
        return Report.from_exposure(
            record, result, exposure, assessment_id=assessment_id or str(uuid4()),
        ).to_dict()
