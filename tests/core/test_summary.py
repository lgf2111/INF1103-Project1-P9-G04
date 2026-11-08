"""Report summary: filter criteria, pluggable metrics, presentation and the CLI flow."""

from unittest.mock import Mock

import pytest

from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager
from phishreport.data.storage import ReportStorage
from phishreport.io import IOManager
from phishreport.logic import LogicManager, ReportFilter, ReportSummarizer, SummaryMetric
from phishreport.logic.summary import (
    ChannelBreakdown,
    PriorityBreakdown,
    ReportedExposure,
    ScoreStatistics,
    StoredReport,
)

HIGH_EMAIL = {
    "schema_version": 2,
    "channel": "email",
    "clicked": True,
    "downloaded": False,
    "submitted_category": "password",
    "result": {"score": 90, "priority": "HIGH"},
}
MEDIUM_SMS = {"channel": "sms", "clicked": False, "result": {"score": 45, "priority": "MEDIUM"}}
LEGACY_LOW = {"channel": "chat", "score": 10, "priority": "low", "message": "hi"}
RECORDS = [HIGH_EMAIL, MEDIUM_SMS, LEGACY_LOW]


class ScriptedTerminal:
    def __init__(self, answers=()):
        self.answers = iter(answers)
        self.prompts = []
        self.lines = []

    def read(self, prompt):
        self.prompts.append(prompt)
        return next(self.answers)

    def write(self, *parts):
        self.lines.append(" ".join(str(part) for part in parts))


class MemoryStorage(ReportStorage):
    """In-memory storage so the flow tests never touch the file system."""

    def __init__(self, records=(), error=None):
        self.records = list(records)
        self.error = error

    def read_records(self):
        if self.error:
            raise self.error
        return list(self.records)

    def write_records(self, records):
        self.records = list(records)


class AcceptAllValidator:
    def validate_stored(self, record):
        return record

    def validate_new(self, record):
        return record


# --- StoredReport hides the two stored layouts -------------------------------------------


def test_stored_report_reads_current_and_legacy_layouts_the_same_way():
    current, legacy = StoredReport(HIGH_EMAIL), StoredReport(LEGACY_LOW)

    assert (current.priority, current.score, current.channel) == ("HIGH", 90, "email")
    assert (legacy.priority, legacy.score, legacy.channel) == ("LOW", 10, "chat")
    assert current.clicked and current.submitted_credentials
    assert not legacy.clicked and not legacy.submitted_credentials


def test_stored_report_ignores_malformed_values_instead_of_guessing():
    report = StoredReport({"channel": 7, "result": {"score": True, "priority": None}})

    assert (report.channel, report.priority, report.score) == (None, None, None)


# --- ReportFilter ------------------------------------------------------------------------


@pytest.mark.parametrize(
    "criteria, expected",
    [
        ({}, 3),
        ({"priority": "high"}, 1),
        ({"priority": "LOW"}, 1),
        ({"channel": "SMS"}, 1),
        ({"min_score": 40}, 2),
        ({"priority": "high", "channel": "sms"}, 0),
        ({"priority": "medium", "min_score": 50}, 0),
    ],
)
def test_report_filter_matches_every_set_criterion(criteria, expected):
    report_filter = ReportFilter(**criteria)

    assert sum(report_filter.matches(record) for record in RECORDS) == expected


@pytest.mark.parametrize(
    "criteria",
    [{"priority": "urgent"}, {"channel": "fax"}, {"min_score": "50"}, {"min_score": True}],
)
def test_report_filter_rejects_unknown_values(criteria):
    with pytest.raises(ValueError):
        ReportFilter(**criteria)


def test_report_filter_describes_its_criteria_for_the_summary_heading():
    assert ReportFilter().describe() == "all reports"
    assert (
        ReportFilter(priority="high", channel="sms", min_score=40).describe()
        == "priority High, channel SMS, score at least 40"
    )


def test_report_filter_leaves_the_record_unchanged():
    record = {"channel": "email", "result": {"score": 90, "priority": "HIGH"}}
    snapshot = {"channel": "email", "result": {"score": 90, "priority": "HIGH"}}

    ReportFilter(priority="high").matches(record)

    assert record == snapshot


# --- Metrics and summarizer --------------------------------------------------------------


def test_default_summary_counts_priorities_channels_scores_and_exposure():
    summary = LogicManager().summarize(RECORDS)
    sections = {section.title: dict(section.rows) for section in summary.sections}

    assert summary.total == 3
    assert sections["Reports by priority"] == {"High": "1", "Medium": "1", "Low": "1"}
    assert sections["Reports by channel"] == {"Email": "1", "SMS": "1", "Chat": "1"}
    assert sections["Rule-based score"] == {"Average": "48.3", "Highest": "90", "Lowest": "10"}
    assert sections["Reported exposure"] == {
        "Clicked a link": "1",
        "Downloaded a file": "0",
        "Submitted a password or code": "1",
    }


def test_metrics_report_values_they_cannot_classify():
    reports = [StoredReport({"channel": "fax", "result": {"priority": "weird"}})]

    assert ("Unavailable", "1") in PriorityBreakdown().compute(reports)
    assert ("Unknown", "1") in ChannelBreakdown().compute(reports)
    assert ScoreStatistics().compute(reports) == [("Scores", "None recorded")]
    assert dict(ReportedExposure().compute(reports))["Clicked a link"] == "0"


def test_summary_of_no_reports_has_a_zero_total():
    summary = LogicManager().summarize([])

    assert summary.total == 0


def test_summarizer_runs_any_metric_subclass_without_being_changed():
    class LongestMessage(SummaryMetric):
        title = "Longest message"

        def compute(self, reports):
            return [("Reports seen", str(len(reports)))]

    summary = ReportSummarizer(metrics=[LongestMessage()]).summarize(RECORDS)

    assert [(s.title, s.rows) for s in summary.sections] == [
        ("Longest message", (("Reports seen", "3"),))
    ]


def test_summary_metric_is_abstract():
    with pytest.raises(TypeError):
        SummaryMetric()


# --- Presentation and filter prompts -----------------------------------------------------


def test_display_summary_lists_every_section():
    terminal = ScriptedTerminal()

    IOManager(terminal).display_summary(LogicManager().summarize(RECORDS), "all reports")

    assert terminal.lines[:3] == ["\n=== Report summary ===", "Showing: all reports", "Reports: 3"]
    assert "\nReports by priority:" in terminal.lines
    assert " - High: 1" in terminal.lines
    assert " - Average: 48.3" in terminal.lines


def test_display_summary_says_when_nothing_matches():
    terminal = ScriptedTerminal()

    IOManager(terminal).display_summary(LogicManager().summarize([]), "priority High")

    assert terminal.lines[-1] == "No saved reports match."
    assert not any("Reports by priority" in line for line in terminal.lines)


def test_collect_summary_filter_accepts_enter_for_all_and_reprompts_on_typos():
    terminal = ScriptedTerminal(["urgent", "High", ""])

    criteria = IOManager(terminal).collect_summary_filter()

    assert criteria == {"priority": "high", "channel": None}
    assert terminal.prompts[1].startswith("Please enter high")


# --- CLI flow ----------------------------------------------------------------------------


def _app(terminal, storage):
    return PhishReportApp(
        io_manager=IOManager(terminal),
        ai_manager=Mock(),
        logic_manager=LogicManager(),
        data_manager=DataManager(storage=storage, validator=AcceptAllValidator()),
    )


def test_summarize_reports_filters_saved_history_before_counting():
    terminal = ScriptedTerminal(["high", ""])

    _app(terminal, MemoryStorage(RECORDS)).summarize_reports()

    assert "Showing: priority High" in terminal.lines
    assert "Reports: 1" in terminal.lines


def test_summarize_reports_with_no_history_reports_zero():
    terminal = ScriptedTerminal(["", ""])

    _app(terminal, MemoryStorage()).summarize_reports()

    assert "Reports: 0" in terminal.lines
    assert "No saved reports match." in terminal.lines


def test_summarize_reports_stops_cleanly_when_history_is_unreadable():
    terminal = ScriptedTerminal()

    _app(terminal, MemoryStorage(error=OSError("denied"))).summarize_reports()

    assert terminal.lines == ["Could not load local report history; existing file preserved."]
    assert terminal.prompts == []


def test_menu_option_five_runs_the_summary_and_six_quits():
    terminal = ScriptedTerminal(["5", "", "", "6"])

    _app(terminal, MemoryStorage(RECORDS)).run()

    assert "\n=== Report summary ===" in terminal.lines
    assert "Bye!" in terminal.lines
