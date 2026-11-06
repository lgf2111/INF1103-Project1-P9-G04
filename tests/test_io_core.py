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
    from io_core import EmlReader

    path = Path(__file__).resolve().parent / "fixtures" / "sample-1.eml"
    reader = EmlReader()

    sender, message = reader.read_bytes(path.read_bytes())

    assert sender
    assert message.startswith("Subject: ")
    assert reader.read_path(path) == (sender, message)


def test_folder_picker_can_select_an_earlier_page_after_an_invalid_answer(tmp_path, monkeypatch):
    from io_core import EmlFolderPicker, EmlReader

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
def test_folder_picker_propagates_terminal_interruption(monkeypatch, interruption):
    from io_core import EmlFolderPicker, EmlReader

    monkeypatch.setattr("local_settings.get_setting", lambda key: None)
    terminal = ScriptedTerminal([interruption()])
    picker = EmlFolderPicker(terminal, EmlReader())

    with pytest.raises(interruption):
        picker.get_eml_from_folder()


def test_report_presenter_shortens_only_the_history_preview():
    from io_core import ReportPresenter

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
