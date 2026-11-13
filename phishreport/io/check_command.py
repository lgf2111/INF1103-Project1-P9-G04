"""Assess a pasted message without depending on its transport."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import ClassVar

from phishreport.assessment import AssessmentSnapshot

from .commands import Command, CommandReply, CommandRequest


@dataclass(frozen=True)
class CheckOutcome:
    """Assessment data retained for a transport to present, save or re-score."""

    record: dict
    result: dict
    findings: dict | None = None


@dataclass
class CheckCommand(Command):
    """Prepare and assess once using services supplied by the transport.

    Successful outcomes replace session['check_outcome']. Input collection,
    saving, presentation and exposure follow-up remain the caller's concern.
    Service exceptions propagate without publishing a partial outcome.
    """

    prepare_record: Callable[[CommandRequest], dict]
    assess_record: Callable[[dict], dict | AssessmentSnapshot]

    name: ClassVar[str] = "check"
    help_text: ClassVar[str] = "Assess a pasted message: /check <text>"

    def execute(self, request: CommandRequest) -> CommandReply:
        """Assess nonempty argument text and publish its complete outcome."""
        if not request.text.strip():
            return CommandReply("Usage: /check <text>", "usage")

        record = self.prepare_record(request)
        assessment = self.assess_record(record)
        if isinstance(assessment, AssessmentSnapshot):
            outcome = CheckOutcome(record, assessment.result, assessment.findings)
        else:
            outcome = CheckOutcome(record, assessment)
        request.session["check_outcome"] = outcome
        return CommandReply("Assessment ready.", "assessment")
