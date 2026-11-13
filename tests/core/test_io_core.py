import os
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

    assert terminal.prompts == ["Choose 1-6: ", "Invalid choice. Please choose 1-6: "]
    assert terminal.lines[0] == "\n=== PhishReport ==="
