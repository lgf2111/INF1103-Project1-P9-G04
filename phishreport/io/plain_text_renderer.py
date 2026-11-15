"""Render neutral assessment documents as plain text."""

from .assessment_document import AssessmentDocument
from .document_renderer import DocumentRenderer, RenderContext


class PlainTextRenderer(DocumentRenderer):
    """Render assessment sections as the existing console/chat text."""

    def render(
        self,
        document: AssessmentDocument,
        context: RenderContext | None = None,
    ) -> str:
        del context  # Alert metadata is not part of a plain assessment result.
        if not document.available:
            return "No assessment available."

        lines = []
        for kind, title, entries in document.sections:
            if kind == "fields":
                lines.append("=== Assessment ===")
                for label, value in entries:
                    if label == "Priority":
                        value = (value or "unavailable").replace("_", " ").title()
                    elif label == "Rule-based score" and value is None:
                        value = "Unavailable"
                    lines.append(f"{label}: {value}")
                continue

            lines.extend(("", f"{title}:"))
            for number, (label, value) in enumerate(entries, start=1):
                if kind == "trace":
                    matched, score = value
                    status = "matched" if matched else "not matched"
                    score_text = f" (score: {score})" if score is not None else ""
                    lines.append(f" - {label}: {status}{score_text}")
                elif kind == "bullets":
                    lines.append(f" - {value}")
                elif kind == "numbered":
                    lines.append(f"{number}. {value}")
        return "\n".join(lines)
