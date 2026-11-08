"""Summarize saved reports with filter criteria and pluggable metrics."""

from abc import ABC, abstractmethod
from collections import Counter
from dataclasses import dataclass

PRIORITIES = ("HIGH", "MEDIUM", "LOW")
CHANNELS = ("email", "sms", "chat")
CHANNEL_LABELS = {"email": "Email", "sms": "SMS", "chat": "Chat"}


class StoredReport:
    """Read-only view of a saved report that hides the two stored layouts.

    Current reports keep the assessment under ``result``. Older eight-field
    reports keep ``score`` and ``priority`` at the top level. Callers see the
    same properties for both.
    """

    def __init__(self, record: dict) -> None:
        self._record = record
        self._result = record.get("result") or record

    @property
    def channel(self) -> str | None:
        value = self._record.get("channel")
        return value.lower() if isinstance(value, str) else None

    @property
    def priority(self) -> str | None:
        value = self._result.get("priority")
        return value.upper() if isinstance(value, str) else None

    @property
    def score(self) -> int | None:
        value = self._result.get("score")
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    @property
    def clicked(self) -> bool:
        return self._record.get("clicked") is True

    @property
    def downloaded(self) -> bool:
        return self._record.get("downloaded") is True

    @property
    def submitted_credentials(self) -> bool:
        return self._record.get("submitted_category") in ("password", "otp")


@dataclass(frozen=True)
class ReportFilter:
    """Criteria for choosing which saved reports to summarize.

    An unset criterion matches everything. Unknown priorities or channels raise
    ValueError so a typo never silently returns an empty summary.
    """

    priority: str | None = None
    channel: str | None = None
    min_score: int | None = None

    def __post_init__(self) -> None:
        if self.priority is not None:
            priority = str(self.priority).upper()
            if priority not in PRIORITIES:
                raise ValueError("Priority must be HIGH, MEDIUM or LOW.")
            object.__setattr__(self, "priority", priority)
        if self.channel is not None:
            channel = str(self.channel).lower()
            if channel not in CHANNELS:
                raise ValueError("Channel must be email, SMS or chat.")
            object.__setattr__(self, "channel", channel)
        if self.min_score is not None and (
            not isinstance(self.min_score, int) or isinstance(self.min_score, bool)
        ):
            raise ValueError("Minimum score must be a whole number.")

    def matches(self, record: dict) -> bool:
        """Return whether a saved record satisfies every set criterion."""
        report = StoredReport(record)
        if self.priority is not None and report.priority != self.priority:
            return False
        if self.channel is not None and report.channel != self.channel:
            return False
        if self.min_score is not None and (report.score is None or report.score < self.min_score):
            return False
        return True

    def describe(self) -> str:
        """Return the active criteria as short text, or 'all reports'."""
        parts = []
        if self.priority is not None:
            parts.append(f"priority {self.priority.title()}")
        if self.channel is not None:
            parts.append(f"channel {CHANNEL_LABELS[self.channel]}")
        if self.min_score is not None:
            parts.append(f"score at least {self.min_score}")
        return ", ".join(parts) if parts else "all reports"


@dataclass(frozen=True)
class SummarySection:
    """One titled block of label and value rows in a summary."""

    title: str
    rows: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class ReportSummary:
    """The number of reports summarized and the sections computed for them."""

    total: int
    sections: tuple[SummarySection, ...]


class SummaryMetric(ABC):
    """Contract for one block of a summary.

    The summarizer treats every metric the same way, so a new statistic is added
    by writing a new subclass, not by changing the summarizer.
    """

    title: str

    @abstractmethod
    def compute(self, reports: list[StoredReport]) -> list[tuple[str, str]]:
        """Return (label, value) rows describing the reports."""


class PriorityBreakdown(SummaryMetric):
    """Count reports by response priority."""

    title = "Reports by priority"

    def compute(self, reports):
        counts = Counter(report.priority for report in reports)
        rows = [(priority.title(), str(counts.pop(priority, 0))) for priority in PRIORITIES]
        if counts:
            rows.append(("Unavailable", str(sum(counts.values()))))
        return rows


class ChannelBreakdown(SummaryMetric):
    """Count reports by the channel they arrived through."""

    title = "Reports by channel"

    def compute(self, reports):
        counts = Counter(report.channel for report in reports)
        rows = [(CHANNEL_LABELS[channel], str(counts.pop(channel, 0))) for channel in CHANNELS]
        if counts:
            rows.append(("Unknown", str(sum(counts.values()))))
        return rows


class ScoreStatistics(SummaryMetric):
    """Report the average, highest and lowest rule-based score."""

    title = "Rule-based score"

    def compute(self, reports):
        scores = [report.score for report in reports if report.score is not None]
        if not scores:
            return [("Scores", "None recorded")]
        return [
            ("Average", f"{sum(scores) / len(scores):.1f}"),
            ("Highest", str(max(scores))),
            ("Lowest", str(min(scores))),
        ]


class ReportedExposure(SummaryMetric):
    """Count reports where the user said they interacted with the message."""

    title = "Reported exposure"

    def compute(self, reports):
        return [
            ("Clicked a link", str(sum(report.clicked for report in reports))),
            ("Downloaded a file", str(sum(report.downloaded for report in reports))),
            (
                "Submitted a password or code",
                str(sum(report.submitted_credentials for report in reports)),
            ),
        ]


class ReportSummarizer:
    """Build a ReportSummary by running each metric over the saved reports."""

    def __init__(self, metrics: list[SummaryMetric] | None = None) -> None:
        self._metrics = tuple(
            metrics
            if metrics is not None
            else (PriorityBreakdown(), ChannelBreakdown(), ScoreStatistics(), ReportedExposure())
        )

    def summarize(self, records: list[dict]) -> ReportSummary:
        """Return counts and statistics for already filtered saved records."""
        reports = [StoredReport(record) for record in records]
        sections = tuple(
            SummarySection(metric.title, tuple(metric.compute(reports))) for metric in self._metrics
        )
        return ReportSummary(total=len(reports), sections=sections)
