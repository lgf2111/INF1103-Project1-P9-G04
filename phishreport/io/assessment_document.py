"""Neutral, ordered content for rendering one assessment."""

from dataclasses import dataclass
from typing import Literal

DocumentEntry = tuple[str, object]
DocumentSection = tuple[
    Literal["fields", "trace", "bullets", "numbered"],
    str,
    tuple[DocumentEntry, ...],
]


@dataclass(frozen=True, slots=True)
class AssessmentDocument:
    """Assessment content without terminal or Telegram formatting."""

    available: bool
    sections: tuple[DocumentSection, ...]
