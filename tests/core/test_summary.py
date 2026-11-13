"""Report summary: filter criteria, pluggable metrics, presentation and the CLI flow."""

from copy import deepcopy
from unittest.mock import Mock

import pytest

from phishreport.assessment import AssessmentService
from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
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


def _exposure_report(clicked=None, downloaded=None, category=None, answered=False):
    return AssessmentService.build_exposure_report(
        {"channel": "chat", "message": "Original message", "sender": "@sender",
         "has_link": True, "link": "https://example.test", "has_file": True,
         "file_name": None},
        {"score": 80, "priority": "HIGH", "reasons": [], "checklist": []},
        {"clicked": clicked, "downloaded": downloaded, "submitted_category": category,
         "disclosure_answered": answered},
    )


@pytest.mark.parametrize(
    "answers,expected",
    [
        ((None, None, None, False), (False, False, False)),
        ((False, False, None, True), (False, False, False)),
        ((True, None, None, False), (True, False, False)),
        ((None, True, None, False), (False, True, False)),
        ((True, False, "password", True), (True, False, True)),
        ((False, True, "otp", True), (False, True, True)),
        ((1, "true", "password", 1), (False, False, False)),
        ((True, True, "otp", False), (True, True, False)),
    ],
    ids=["unknown", "confirmed-no", "partial-click", "partial-download", "password",
         "otp", "truthy-not-confirmed", "unconfirmed-disclosure"],
)
def test_stored_report_v3_uses_confirmed_nested_answers_over_stale_root(answers, expected):
    record = _exposure_report(*answers)
    record.update(clicked=not expected[0], downloaded=not expected[1],
                  submitted_category=None if expected[2] else "password")
    # Nested extras must not replace saved metadata or the original assessment.
    record["exposure"].update(channel="email", message="replacement",
                              result={"score": 0, "priority": "LOW"})
    before = deepcopy(record)

    report = StoredReport(record)

    assert (report.clicked, report.downloaded, report.submitted_credentials) == expected
    assert (report.channel, report.priority, report.score) == ("chat", "HIGH", 80)
    assert ReportFilter(channel="chat", priority="HIGH", min_score=80).matches(record)
    assert record == before


@pytest.mark.parametrize("exposure", [None, [], "unknown", 1, {}])
def test_stored_report_v3_malformed_exposure_never_falls_back_to_root(exposure):
    record = _exposure_report()
    record.update(exposure=exposure, clicked=True, downloaded=True, submitted_category="otp")
    before = deepcopy(record)

    report = StoredReport(record)

    assert (report.clicked, report.downloaded, report.submitted_credentials) == (
        False, False, False,
    )
    assert record == before


def test_stored_report_v3_missing_exposure_never_falls_back_to_root():
    record = {"schema_version": 3, "clicked": True, "downloaded": True,
              "submitted_category": "password"}

    report = StoredReport(record)

    assert (report.clicked, report.downloaded, report.submitted_credentials) == (
        False, False, False,
    )


@pytest.mark.parametrize("category", ["password", "otp", ["password"], {"category": "otp"}])
def test_stored_report_v3_unanswered_disclosure_ignores_even_malformed_category(category):
    report = StoredReport(_exposure_report(category=category))

    assert report.submitted_credentials is False


@pytest.mark.parametrize("version", [None, 1, 2], ids=["unversioned", "v1", "v2"])
def test_stored_report_historical_root_actions_ignore_nested_exposure(version):
    record = {"clicked": True, "downloaded": True, "submitted_category": "otp",
              "channel": "SMS", "score": 90, "priority": "high",
              "exposure": {"clicked": False, "downloaded": False}}
    if version is not None:
        record["schema_version"] = version
    before = deepcopy(record)

    report = StoredReport(record)

    assert (report.clicked, report.downloaded, report.submitted_credentials) == (True, True, True)
    assert (report.channel, report.priority, report.score) == ("sms", "HIGH", 90)
    assert record == before


def test_mixed_history_summary_counts_nested_actions_and_preserves_other_metrics():
    records = [*deepcopy(RECORDS), _exposure_report(True), _exposure_report(downloaded=True),
               _exposure_report(category="otp", answered=True), _exposure_report()]

    summary = LogicManager().summarize(records)
    sections = {section.title: dict(section.rows) for section in summary.sections}

    assert summary.total == 7
    assert sections["Reported exposure"] == {
        "Clicked a link": "2", "Downloaded a file": "1", "Submitted a password or code": "2",
    }
    assert sections["Reports by priority"] == {"High": "5", "Medium": "1", "Low": "1"}
    assert sections["Reports by channel"] == {"Email": "1", "SMS": "1", "Chat": "5"}
    assert sections["Rule-based score"] == {"Average": "66.4", "Highest": "90", "Lowest": "10"}


@pytest.mark.parametrize("storage_type", [JsonReportStorage, SqliteReportStorage])
def test_saved_v3_answers_survive_real_reload_and_summary(tmp_path, storage_type):
    path = tmp_path / "history"
    records = [_exposure_report(), _exposure_report(False, False, None, True),
               _exposure_report(True), _exposure_report(downloaded=True),
               _exposure_report(category="password", answered=True),
               _exposure_report(category="otp", answered=True)]
    before = deepcopy(records)
    manager = DataManager(storage=storage_type(path))
    for record in records:
        manager.save(record)

    loaded = DataManager(storage=storage_type(path)).load(strict=True)
    summary = LogicManager().summarize(loaded)
    sections = {section.title: dict(section.rows) for section in summary.sections}

    assert loaded == records == before
    assert summary.total == 6
    assert sections["Reported exposure"] == {
        "Clicked a link": "1", "Downloaded a file": "1", "Submitted a password or code": "2",
    }
    assert sections["Reports by priority"] == {"High": "6", "Medium": "0", "Low": "0"}
    assert sections["Reports by channel"] == {"Email": "0", "SMS": "0", "Chat": "6"}
    assert sections["Rule-based score"] == {"Average": "80.0", "Highest": "80", "Lowest": "80"}


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
