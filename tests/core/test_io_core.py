import os
from copy import deepcopy
from pathlib import Path

import pytest


class ScriptedTerminal:
    def __init__(self, answers=()):
        self.answers = iter(answers)
        self.prompts = []
        self.lines = []

    def read(self, prompt: str) -> str:
        self.prompts.append(prompt)
        answer = next(self.answers)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def write(self, *parts: object) -> None:
        self.lines.append(" ".join(str(part) for part in parts))


def test_eml_reader_decodes_fixture_from_bytes_and_path():
    from phishreport.io import EmlReader

    path = Path(__file__).resolve().parents[1] / "fixtures" / "sample-1.eml"
    reader = EmlReader()

    sender, message = reader.read_bytes(path.read_bytes())

    assert sender
    assert message.startswith("Subject: ")
    assert reader.read_path(path) == (sender, message)


def test_folder_picker_can_select_an_earlier_page_after_an_invalid_answer(tmp_path, monkeypatch):
    from phishreport.io import EmlFolderPicker, EmlReader

    monkeypatch.chdir(tmp_path)
    folder = Path("inbox")
    folder.mkdir()
    for number in range(1, 7):
        path = folder / f"message-{number}.eml"
        path.write_bytes(f"From: fictional@example.test\r\n\r\nMessage {number}.".encode())
        modified = 1_700_000_000 + number
        os.utime(path, (modified, modified))
    Path(".phishreport_config.json").write_text('{"eml_folder": "inbox"}', encoding="utf-8")
    terminal = ScriptedTerminal(["6", "1"])
    picker = EmlFolderPicker(terminal, EmlReader())

    assert picker.get_eml_from_folder() == ("fictional@example.test", "Message 6.")
    assert terminal.prompts == [
        "Enter a number to pick a file, 'm' for more, or 'c' to cancel: ",
        "Enter a number to pick a file, or 'c' to cancel: ",
    ]
    assert terminal.lines == [
        "1. message-6.eml",
        "2. message-5.eml",
        "3. message-4.eml",
        "4. message-3.eml",
        "5. message-2.eml",
        "Invalid choice. Please try again.",
        "6. message-1.eml",
        "Email loaded successfully.",
    ]


@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_folder_picker_propagates_terminal_interruption(tmp_path, interruption):
    from phishreport.io import EmlFolderPicker, EmlReader
    from phishreport.local_settings import LocalSettings

    settings = LocalSettings(str(tmp_path / "missing.json"))
    terminal = ScriptedTerminal([interruption()])
    picker = EmlFolderPicker(terminal, EmlReader(), settings)

    with pytest.raises(interruption):
        picker.get_eml_from_folder()


def test_report_presenter_shortens_only_the_history_preview():
    from phishreport.io import ReportPresenter

    message = "0123456789\n0123456789 0123456789 0123456789 0123456789"
    record = {"channel": "chat", "message": message, "priority": "review", "score": 0}
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_list([record])

    assert terminal.lines == [
        "\n=== Saved reports ===",
        "1. Chat | Review | Score: 0",
        "   0123456789 0123456789 0123456789 0123456789 012...",
    ]
    assert record == {"channel": "chat", "message": message, "priority": "review", "score": 0}


def test_display_list_tolerates_mixed_history_without_changing_records():
    from phishreport.io import ReportPresenter

    records = [
        {"channel": "sms", "message": "  First\n\tmessage ", "score": 0, "priority": "LOW"},
        {"channel": ["email"], "message": {"text": "invalid"},
         "result": {"priority": ["HIGH"], "score": True}},
        {"channel": "email", "message": "x" * 50,
         "result": {"priority": "urgent_review", "score": 101.5}},
        {"channel": "chat", "message": "y" * 51, "result": "malformed",
         "priority": "review", "score": -2.5},
        {},
    ]
    before = deepcopy(records)
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_list(records)

    assert terminal.lines == [
        "\n=== Saved reports ===",
        "1. SMS | Low | Score: 0", "   First message",
        "2. Unknown | Unavailable | Score: Unavailable", "   ",
        "3. Email | Urgent Review | Score: 101.5", "   " + "x" * 50,
        "4. Chat | Review | Score: -2.5", "   " + "y" * 47 + "...",
        "5. Unknown | Unavailable | Score: Unavailable", "   ",
    ]
    assert records == before


@pytest.mark.parametrize("score", [None, "invalid", True, [], {}, float("nan"), float("inf")])
def test_display_list_marks_unknown_scores_unavailable(score):
    from phishreport.io import ReportPresenter

    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_list([{"result": {"priority": "LOW", "score": score}}])

    assert terminal.lines == [
        "\n=== Saved reports ===", "1. Unknown | Low | Score: Unavailable", "   ",
    ]


@pytest.mark.parametrize("nested,expected", [
    ({}, "Low | Score: 0"),
    (None, "Low | Score: 0"),
    ({"priority": "HIGH"}, "High | Score: Unavailable"),
    ({"score": 60}, "Unavailable | Score: 60"),
    ({"historical_metadata": True}, "Unavailable | Score: Unavailable"),
])
def test_display_list_selects_nested_result_without_merging_root_fields(nested, expected):
    from phishreport.io import ReportPresenter

    record = {"channel": "chat", "priority": "LOW", "score": 0, "result": nested}
    before = deepcopy(record)
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_list([record])

    assert terminal.lines == ["\n=== Saved reports ===", f"1. Chat | {expected}", "   "]
    assert record == before


@pytest.mark.parametrize("typed", [False, True], ids=["dictionary", "model"])
def test_display_result_preserves_guidance_and_validated_trace_order(typed):
    from phishreport.io import ReportPresenter
    from phishreport.model import AssessmentResult, RuleTrace

    result = {
        "score": 80, "priority": "urgent_review", "matched_rule": "Clicked link",
        "reasons": ["  First reason\n ", "Second reason"],
        "checklist": ["  First action  ", "Second action"],
        "trace": [
            {"rule_name": "Disclosure", "matched": False, "score": None},
            {"rule_name": "Clicked link", "matched": True, "score": 80},
        ],
    }
    before = deepcopy(result)
    if typed:
        result = AssessmentResult(
            80, "urgent_review", result["reasons"], result["checklist"], "Clicked link",
            [RuleTrace("Disclosure", False), RuleTrace("Clicked link", True, 80)],
        )
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_result(result)

    assert terminal.lines == [
        "\n=== Assessment ===", "Priority: Urgent Review", "Rule-based score: 80",
        "Matched rule: Clicked link", "\nRule evaluation trace:",
        " - Disclosure: not matched", " - Clicked link: matched (score: 80)",
        "\nReasons:", " -   First reason\n ", " - Second reason",
        "\nRecommended actions:", "1.   First action  ", "2. Second action",
    ]
    if not typed:
        assert result == before


@pytest.mark.parametrize("fields", [
    {}, {"score": None}, {"score": "invalid"}, {"score": True},
    {"score": float("nan")}, {"score": float("inf")},
])
def test_display_result_reports_unknown_scores_without_inventing_zero(fields):
    from phishreport.io import ReportPresenter

    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_result({"priority": "LOW", **fields})

    assert terminal.lines == [
        "\n=== Assessment ===", "Priority: Low", "Rule-based score: Unavailable",
        "\nRecommended actions:",
    ]


def test_display_result_tolerates_partial_malformed_guidance_and_priority():
    from phishreport.io import ReportPresenter

    result = {"score": 0, "priority": ["HIGH"], "matched_rule": 7,
              "reasons": [" Keep reason ", None, 3, ""], "checklist": "not a list"}
    before = deepcopy(result)
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_result(result)

    assert terminal.lines == [
        "\n=== Assessment ===", "Priority: Unavailable", "Rule-based score: 0",
        "\nReasons:", " -  Keep reason ", " - ", "\nRecommended actions:",
    ]
    assert result == before


@pytest.mark.parametrize("trace", [
    ["malformed step"],
    [{"rule_name": "Claimed rule", "matched": "yes", "score": 80}],
    [{"rule_name": "Claimed rule", "matched": True, "score": 90}],
])
def test_display_result_omits_unvalidated_trace(trace):
    from phishreport.io import ReportPresenter

    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_result({
        "score": 80, "matched_rule": "Claimed rule", "trace": trace,
    })

    assert terminal.lines == [
        "\n=== Assessment ===", "Priority: Unavailable", "Rule-based score: 80",
        "Matched rule: Claimed rule", "\nRecommended actions:",
    ]


@pytest.mark.parametrize("result", [None, {}])
def test_display_result_describes_absent_assessment(result):
    from phishreport.io import ReportPresenter

    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_result(result)

    assert terminal.lines == ["\nNo assessment available."]


@pytest.fixture
def exposure_record():
    return {
        "schema_version": 3,
        "channel": "chat",
        "sender": " @original ",
        "message": "  Original message\nKeep this text.  ",
        "has_link": True,
        "link": "https://example.test/verify?ref=original",
        "has_file": True,
        "file_name": "notice.pdf",
        "exposure": {
            "clicked": None,
            "downloaded": None,
            "submitted_category": None,
            "disclosure_answered": False,
        },
        "result": {
            "score": 60,
            "priority": "MEDIUM",
            "reasons": ["Saved reason."],
            "checklist": ["Saved recommendation."],
        },
    }


@pytest.mark.parametrize(
    "clicked,downloaded,category,answered,score,priority,expected,unconfirmed",
    [
        (None, None, None, False, 60, "MEDIUM",
         ["Unconfirmed", "Unconfirmed", "Unconfirmed"], True),
        (False, False, None, True, 60, "MEDIUM",
         ["No", "No", "None reported"], False),
        (True, None, None, False, 80, "HIGH",
         ["Yes", "Unconfirmed", "Unconfirmed"], True),
        (None, True, "otp", True, 90, "HIGH",
         ["Unconfirmed", "Yes", "One-time code"], True),
        (True, False, "password", True, 90, "HIGH",
         ["Yes", "No", "Password"], False),
        (False, True, None, False, 80, "HIGH",
         ["No", "Yes", "Unconfirmed"], True),
    ],
    ids=["unknown", "confirmed-none", "partial-clicked", "partial-otp", "password",
         "unanswered-disclosure"],
)
def test_display_record_preserves_v3_exposure_and_saved_assessment(
    exposure_record, clicked, downloaded, category, answered, score, priority,
    expected, unconfirmed,
):
    from phishreport.io import ReportPresenter

    record = exposure_record
    record["exposure"] = {
        "clicked": clicked,
        "downloaded": downloaded,
        "submitted_category": category,
        "disclosure_answered": answered,
    }
    record["result"].update(score=score, priority=priority)
    before = deepcopy(record)
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_record(record)

    assert terminal.lines[:7] == [
        "\n=== Report details ===", "Channel: Chat", "Sender:  @original ", "Message:",
        "  Original message\nKeep this text.  ",
        "Included link: https://example.test/verify?ref=original", "Included file: notice.pdf",
    ]
    assert terminal.lines[7:10] == [
        f"Clicked link: {expected[0]}", f"Downloaded file: {expected[1]}",
        f"Information submitted: {expected[2]}",
    ]
    assert ("Exposure unconfirmed" in terminal.lines) is unconfirmed
    assert terminal.lines[-7:] == [
        "\n=== Assessment ===", f"Priority: {priority.title()}", f"Rule-based score: {score}",
        "\nReasons:", " - Saved reason.", "\nRecommended actions:",
        "1. Saved recommendation.",
    ]
    assert record == before


@pytest.mark.parametrize(
    "has_link,link,has_file,file_name,expected_link,expected_file",
    [
        (True, "https://example.test/path?a=1", True, None,
         "https://example.test/path?a=1", "Mentioned (filename unknown)"),
        (False, None, False, None, "None reported", "None reported"),
    ],
    ids=["extracted-link-generic-file", "no-link-or-file"],
)
def test_display_record_v3_describes_metadata_without_inventing_attachments(
    exposure_record, has_link, link, has_file, file_name, expected_link, expected_file,
):
    from phishreport.io import ReportPresenter

    exposure_record.update(has_link=has_link, link=link, has_file=has_file, file_name=file_name)
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_record(exposure_record)

    assert terminal.lines[5:7] == [
        f"Included link: {expected_link}", f"Included file: {expected_file}",
    ]


@pytest.mark.parametrize("version", [None, 1, 2], ids=["unversioned", "v1", "v2"])
def test_display_record_preserves_exact_historical_rendering(version):
    from phishreport.io import ReportPresenter

    record = {
        "channel": "sms", "message": "Original message",
        "result": {"score": 0, "priority": "LOW", "reasons": [], "checklist": []},
    }
    if version is not None:
        record["schema_version"] = version
    if version != 2:
        record.update(sender="Original sender", link="https://example.test/old",
                      file_name="old.pdf", clicked=True, downloaded=False,
                      submitted_category="otp", has_link=True, has_file=True)
    before = deepcopy(record)
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_record(record)

    assert terminal.lines == [
        "\n=== Report details ===", "Channel: SMS",
        "Sender: Unknown" if version == 2 else "Sender: Original sender",
        "Message:", "Original message",
        "Included link: None reported" if version == 2 else "Included link: https://example.test/old",
        "Included file: None reported" if version == 2 else "Included file: old.pdf",
        "Clicked link: Not recorded" if version == 2 else "Clicked link: Yes",
        "Downloaded file: Not recorded" if version == 2 else "Downloaded file: No",
        ("Information submitted: None reported" if version == 2
         else "Information submitted: One-time code"),
        "\n=== Assessment ===", "Priority: Low", "Rule-based score: 0",
        "\nRecommended actions:",
    ]
    assert record == before


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_saved_v3_partial_exposure_displays_after_reload(tmp_path, backend, exposure_record):
    from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
    from phishreport.io import ReportPresenter

    storage_type = JsonReportStorage if backend == "json" else SqliteReportStorage
    path = tmp_path / f"reports.{backend}"
    exposure_record["exposure"]["clicked"] = True
    exposure_record["file_name"] = None
    exposure_record["result"].update(score=80, priority="HIGH")
    before = deepcopy(exposure_record)
    DataManager(storage=storage_type(path)).save(exposure_record)

    loaded = DataManager(storage=storage_type(path)).load(strict=True)
    terminal = ScriptedTerminal()
    ReportPresenter(terminal).display_record(loaded[0])

    assert "Clicked link: Yes" in terminal.lines
    assert "Downloaded file: Unconfirmed" in terminal.lines
    assert "Information submitted: Unconfirmed" in terminal.lines
    assert "Exposure unconfirmed" in terminal.lines
    assert "Included link: https://example.test/verify?ref=original" in terminal.lines
    assert "Included file: Mentioned (filename unknown)" in terminal.lines
    assert "Priority: High" in terminal.lines
    assert "Rule-based score: 80" in terminal.lines
    assert "Sender:  @original " in terminal.lines
    assert "  Original message\nKeep this text.  " in terminal.lines
    assert loaded == [before]
    assert exposure_record == before


@pytest.mark.parametrize("backend", ["json", "sqlite"])
def test_plain_v3_history_does_not_invent_exposure_answers(tmp_path, backend):
    from phishreport.assessment import AssessmentService
    from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
    from phishreport.io import ReportPresenter

    record = AssessmentService.build_report(
        {"channel": "chat", "message": " Original message\n "},
        {"assessment_id": "existing-id", "score": 0, "priority": "LOW",
         "reasons": [], "checklist": []},
    )
    before = deepcopy(record)
    storage_type = JsonReportStorage if backend == "json" else SqliteReportStorage
    path = tmp_path / f"reports.{backend}"
    DataManager(storage=storage_type(path)).save(record)
    loaded = DataManager(storage=storage_type(path)).load(strict=True)
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_record(loaded[0])

    assert terminal.lines == [
        "\n=== Report details ===", "Channel: Chat", "Sender: Unknown", "Message:",
        " Original message\n ", "Included link: None reported", "Included file: None reported",
        "Clicked link: Not recorded", "Downloaded file: Not recorded",
        "Information submitted: None reported", "\n=== Assessment ===", "Priority: Low",
        "Rule-based score: 0", "\nRecommended actions:",
    ]
    assert loaded == [before]
    assert record == before


@pytest.mark.parametrize("nested", [None, {}, {"clicked": None}])
def test_v3_history_never_falls_back_to_root_exposure(nested):
    from phishreport.io import ReportPresenter

    record = {"schema_version": 3, "channel": "chat", "message": "Original",
              "clicked": True, "downloaded": True, "submitted_category": "password"}
    if nested is not None:
        record["exposure"] = nested
    before = deepcopy(record)
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_record(record)

    missing = "Not recorded" if nested is None else "Unconfirmed"
    assert terminal.lines[7:10] == [
        f"Clicked link: {missing}", f"Downloaded file: {missing}",
        "Information submitted: None reported" if nested is None
        else "Information submitted: Unconfirmed",
    ]
    assert ("Exposure unconfirmed" in terminal.lines) is (nested is not None)
    assert record == before


def test_display_record_projects_legacy_root_assessment_without_mutation():
    from phishreport.io import ReportPresenter

    record = {"channel": "sms", "message": "Historical", "score": 0, "priority": "LOW",
              "reasons": [" Original reason "], "checklist": [" Original action "]}
    before = deepcopy(record)
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_record(record)

    assert terminal.lines[-7:] == [
        "\n=== Assessment ===", "Priority: Low", "Rule-based score: 0", "\nReasons:",
        " -  Original reason ", "\nRecommended actions:", "1.  Original action ",
    ]
    assert record == before


@pytest.mark.parametrize("score", [{}, {"score": None}, {"score": "invalid"}])
def test_display_record_describes_unknown_assessment_score_as_unavailable(score):
    from phishreport.io import ReportPresenter

    record = {"result": {"priority": "LOW", **score}}
    before = deepcopy(record)
    terminal = ScriptedTerminal()

    ReportPresenter(terminal).display_record(record)

    assert "Rule-based score: Unavailable" in terminal.lines
    assert record == before


def test_io_manager_builds_the_same_record_through_all_three_routes(tmp_path, monkeypatch):
    from phishreport.io import IOManager

    monkeypatch.chdir(tmp_path)
    raw = b"From: fictional@example.test\r\n\r\nVerify your account."
    Path("message.eml").write_bytes(raw)
    Path(".phishreport_config.json").write_text('{"eml_folder": "."}', encoding="utf-8")
    exposure_answers = [" YES ", " ", " https://example.test/verify ", "No", " Y ", " OTP "]
    terminal = ScriptedTerminal(
        [
            " EMAIL ",
            " fictional@example.test ",
            "Verify your account.",
            "END",
            *exposure_answers,
            "1",
            *exposure_answers,
            *exposure_answers,
        ]
    )
    manager = IOManager(terminal)

    expected = {
        "channel": "email",
        "sender": "fictional@example.test",
        "message": "Verify your account.",
        "has_link": True,
        "link": "https://example.test/verify",
        "has_file": False,
        "file_name": None,
        "clicked": True,
        "downloaded": False,
        "submitted_category": "otp",
    }
    assert manager.collect_input() == expected
    assert manager.collect_input_from_folder() == expected
    upload = {"filename": "message.EML", "content": raw}
    assert manager.collect_input_from_upload(upload) == expected

    exposure_prompts = [
        "Was a link included? (yes/no): ",
        "Enter the link: ",
        "Link cannot be blank. Please enter the link: ",
        "Was a file included? (yes/no): ",
        "Did you click the link? (yes/no): ",
        "Did you give a password or code? (password/otp/no): ",
    ]
    assert terminal.prompts == [
        "Enter channel (Email/SMS/Chat): ",
        "Enter sender information (press Enter if unknown): ",
        "Enter the suspicious message: ", "",
        *exposure_prompts,
        "Enter a number to pick a file, or 'c' to cancel: ",
        *exposure_prompts,
        *exposure_prompts,
    ]
    assert terminal.lines == [
    "Paste your message. Type END on its own line to finish.",
    "1. message.eml",
    "Email loaded successfully.",
]


@pytest.mark.parametrize(
    ("filename", "content"),
    [("wrong.pdf", b"From: fictional@example.test\r\n\r\nHello"), ("empty.eml", b"")],
)
def test_io_manager_rejects_an_invalid_upload_before_exposure_questions(filename, content):
    from phishreport.io import IOManager

    terminal = ScriptedTerminal()

    with pytest.raises(ValueError):
        IOManager(terminal).collect_input_from_upload({"filename": filename, "content": content})

    assert terminal.prompts == []


@pytest.mark.parametrize("interruption", [EOFError, KeyboardInterrupt])
def test_io_manager_propagates_menu_interruption(interruption):
    from phishreport.io import IOManager

    terminal = ScriptedTerminal(["wrong", interruption()])

    with pytest.raises(interruption):
        IOManager(terminal).main_menu()

    assert terminal.prompts == ["Choose 1-7: ", "Invalid choice. Please choose 1-7: "]
    assert terminal.lines[0] == "\n=== PhishReport ==="
