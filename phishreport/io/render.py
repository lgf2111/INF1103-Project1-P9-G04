"""Build a neutral document from an assessment result."""

from .assessment_document import AssessmentDocument, DocumentSection


class AssessmentRenderer:
    """Project an assessment result into ordered, labelled sections."""

    def render(self, result: dict | None) -> AssessmentDocument:
        """Return result fields in a format-independent document."""
        if not result:
            return AssessmentDocument(available=False, sections=())

        priority = result.get("priority") or "unavailable"
        score = result.get("score") if "score" in result else None
        fields = [
            ("Priority", priority),
            ("Rule-based score", score),
        ]
        if result.get("matched_rule"):
            fields.append(("Matched rule", result["matched_rule"]))

        sections: list[DocumentSection] = [
            ("fields", "Assessment", tuple(fields)),
        ]

        trace = result.get("trace") or []
        if trace:
            trace_entries = []
            for step in trace:
                rule_name = str(step.get("rule_name", "Unknown rule"))
                trace_entries.append((rule_name, (bool(step.get("matched")), step.get("score"))))
            sections.append(("trace", "Rule evaluation trace", tuple(trace_entries)))

        reasons = result.get("reasons") or []
        if reasons:
            sections.append((
                "bullets",
                "Reasons",
                tuple(("Reason", reason) for reason in reasons),
            ))

        checklist = result.get("checklist") or []
        sections.append((
            "numbered",
            "Recommended actions",
            tuple(("Action", step) for step in checklist),
        ))
        return AssessmentDocument(available=True, sections=tuple(sections))
