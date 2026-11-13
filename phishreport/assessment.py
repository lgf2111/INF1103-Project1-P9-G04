"""Shared assessment workflow used by every interface.

The CLI and the Telegram bot both turn an input record into an outcome the same
way: the AI Manager produces validated findings, and the Logic Manager applies
the business rules to the record enriched with those findings. Keeping the steps
here means both interfaces share one definition of an assessment.
"""


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
        return self.assess_with_findings(record)[0]

    def assess_with_findings(self, record: dict) -> tuple[dict, dict]:
        """Return the evaluated outcome and the AI findings that produced it.

        The findings are kept so a follow-up answer (for example the exposure
        question) can be scored again without calling the AI a second time.
        """
        findings = self._ai_manager.assess(record)
        # Enrich a new dictionary only after every AI check passes.
        return self._logic_manager.evaluate({**record, "ai": findings}), findings

    def reassess(self, record: dict, findings: dict) -> dict:
        """Re-score a record with findings already obtained; never calls the AI."""
        return self._logic_manager.evaluate({**record, "ai": findings})

    @staticmethod
    def build_report(record: dict, result: dict) -> dict:
        """Return the version-2 report that keeps the message and its assessment."""
        return {
            "schema_version": 2,
            "channel": record["channel"],
            "message": record["message"],
            "result": result,
        }
