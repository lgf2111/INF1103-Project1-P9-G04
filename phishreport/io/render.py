"""Build a neutral document from the canonical assessment view."""

from phishreport.model import AssessmentResult, Report

from .assessment_document import AssessmentDocument, DocumentSection


class AssessmentRenderer:
    """Project typed or historical assessment results into ordered sections."""

    def render(self, result: AssessmentResult | dict | None) -> AssessmentDocument:
        """Read tolerant model attributes without mutating or rebuilding the payload."""
        assessment = (
            result if isinstance(result, AssessmentResult) else Report({"result": result}).result
        )
        if assessment is None:
            return AssessmentDocument(available=False, sections=())

        fields = [
            ("Priority", assessment.priority or "unavailable"),
            ("Rule-based score", assessment.score),
        ]
        if assessment.matched_rule:
            fields.append(("Matched rule", assessment.matched_rule))

        sections: list[DocumentSection] = [
            ("fields", "Assessment", tuple(fields)),
        ]
        if assessment.trace:
            sections.append((
                "trace",
                "Rule evaluation trace",
                tuple((step.rule_name, (step.matched, step.score)) for step in assessment.trace),
            ))
        if assessment.reasons:
            sections.append((
                "bullets",
                "Reasons",
                tuple(("Reason", reason) for reason in assessment.reasons),
            ))
        sections.append((
            "numbered",
            "Recommended actions",
            tuple(("Action", step) for step in assessment.checklist),
        ))
        return AssessmentDocument(available=True, sections=tuple(sections))
