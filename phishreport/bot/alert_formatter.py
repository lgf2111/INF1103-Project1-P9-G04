"""Telegram adapter for safely formatted phishing alert messages."""

from dataclasses import replace
from html import escape

from phishreport.io.assessment_document import AssessmentDocument
from phishreport.io.html_alert_renderer import HTMLAlertRenderer
from phishreport.io.render import AssessmentRenderer


class PhishingAlertFormatter:
    """Prepare Telegram-safe values and render a Gmail phishing alert."""

    MAX_LINE = 300
    MAX_STEPS = 5

    def __init__(self) -> None:
        self._assessment_renderer = AssessmentRenderer()
        self._html_renderer = HTMLAlertRenderer()

    def _clip(self, text: str) -> str:
        text = " ".join(str(text).split())
        return escape(text if len(text) <= self.MAX_LINE else text[: self.MAX_LINE - 3] + "...")

    def _prepare_document(self, document: AssessmentDocument) -> AssessmentDocument:
        """Escape dynamic HTML values and apply Telegram alert limits."""
        sections = []
        for kind, title, entries in document.sections:
            if kind == "numbered":
                entries = entries[: self.MAX_STEPS]
            safe_entries = []
            for label, value in entries:
                safe_label = self._clip(label) if kind == "trace" else escape(label)
                if kind == "trace":
                    matched, score = value
                    safe_value = (matched, escape(str(score)) if score is not None else None)
                elif value is None:
                    safe_value = None
                elif kind in ("bullets", "numbered") or label == "Matched rule":
                    safe_value = self._clip(str(value))
                else:
                    safe_value = escape(str(value))
                safe_entries.append((safe_label, safe_value))
            sections.append((kind, title, tuple(safe_entries)))
        return replace(document, sections=tuple(sections))

    def format(
        self, result: dict, sender: str | None, subject: str = "", source_url: str | None = None
    ) -> str:
        document = self._prepare_document(self._assessment_renderer.render(result))
        context = {
            "sender": self._clip(sender or "Unknown sender"),
            "subject": self._clip(subject) if subject else None,
            "source_url": escape(source_url, quote=True) if source_url else None,
        }
        return self._html_renderer.render(document, context)
