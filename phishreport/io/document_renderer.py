"""Shared rendering contract for assessment document formats."""

from collections.abc import Mapping
from typing import Protocol

from .assessment_document import AssessmentDocument

RenderContext = Mapping[str, str | None]


class DocumentRenderer(Protocol):
    """Render an assessment document, optionally with alert-specific context."""

    def render(
        self,
        document: AssessmentDocument,
        context: RenderContext | None = None,
    ) -> str:
        """Return the rendered document as text."""
        ...
