"""Coordinate the CLI menu, input routes, and report presentation."""

import sys

from .eml import EmlReader
from .exposure_screen import (
    NUMBERED_HEADING,
    NUMBERED_PROMPT,
    ExposureScreen,
    build_exposure,
    parse_numbered_selection,
    tty_supported,
)
from .folder import EmlFolderPicker
from .presenter import ReportPresenter
from .record_builder import InputDeriver
from .terminal import Terminal

UPLOAD_TYPE_MESSAGE = (
    "Only .eml email files are supported. Images and attachments are not analysed."
)


class IOManager:
    """Collect incident records and display reports through a shared terminal."""

    supports_post_verdict_exposure = True

    def __init__(self, terminal: Terminal, *, stdin=None, stdout=None) -> None:
        self._terminal = terminal
        self._stdin = stdin
        self._stdout = stdout
        self.eml_reader = EmlReader()
        self.folder_picker = EmlFolderPicker(terminal, self.eml_reader)
        self._presenter = ReportPresenter(terminal)

    def main_menu(self) -> str:
        """Return a normalized menu number, keyword or untouched slash input."""
        self._terminal.write("\n=== PhishReport ===")
        self._terminal.write("1. Check a message")
        self._terminal.write("2. View saved reports")
        self._terminal.write("3. Summarize saved reports")
        self._terminal.write("4. Filter and export saved reports")
        self._terminal.write("5. Quit")
        self._terminal.write("Or type a slash command: /check <message>, /status, /help")

        prompt = "Choose 1-5 or a /command: "
        while True:
            choice = self._terminal.read(prompt)
            if choice.lstrip().startswith("/"):
                return choice
            normalized = choice.strip().lower()
            if normalized in ("1", "2", "3", "4", "5", "upload", "feedback"):
                return normalized
            prompt = "Invalid choice. Please choose 1-5, a /command, upload or feedback: "

    def get_valid_choice(self, prompt, valid_choices, error_message):
        """Prompt until stripped, lowercase input matches one of valid_choices.

        Print error_message after an invalid answer. EOF and keyboard interruption
        propagate to the main loop for a consistent application exit.
        """
        choice = self._terminal.read(prompt).strip().lower()

        while choice not in valid_choices:
            choice = self._terminal.read(error_message).strip().lower()

        return choice

    def collect_input(self) -> dict:
        """Collect the message and derive its inputs without follow-up questions."""
        return self.build_record_from_message(self.get_message())

    def build_record_from_message(
        self, message: str, channel: str | None = None, sender: str | None = None
    ) -> dict:
        """Build a record from message text, deriving channel, sender, link and file.

        Manual, folder and upload collection all use this single action/record
        contract. A channel or sender supplied by the caller (an uploaded email)
        takes precedence; otherwise they come from the text. Exposure starts
        unconfirmed so the first saved report is a plain assessment; the
        post-verdict checklist can replace it later.
        """
        derived = InputDeriver.derive_inputs(message)
        inferred = channel is None
        channel = derived["channel"] if inferred else channel
        sender = derived["sender"] if sender is None else sender
        if inferred:
            self._terminal.write(f"Detected: {channel}")
        return {
            "channel": channel,
            "sender": sender,
            "message": message,
            "has_link": derived["has_link"],
            "link": derived["link"],
            "has_file": derived["has_file"],
            "file_name": derived["file_name"],
            "clicked": False,
            "downloaded": False,
            "submitted_category": None,
            "disclosure_answered": False,
        }

    def collect_input_from_upload(self, upload) -> dict:
        """Use the folder import's MIME parser and derived record contract for uploads."""
        if not upload["filename"].lower().endswith(".eml"):
            raise ValueError(UPLOAD_TYPE_MESSAGE)
        sender, message = self.eml_reader.read_bytes(upload["content"])
        return self.build_record_from_message(message, channel="email", sender=sender)

    def show_upload_instructions(self, host, port) -> None:
        """Print the browser upload address and waiting instructions; do not start a server."""
        self._terminal.write(
            f"\nOpen http://{host}:{port} in your browser to upload an .eml email."
        )
        self._terminal.write("Waiting for upload... (Ctrl+C to cancel)")

    def collect_input_from_folder(self) -> dict | None:
        """Load a selected email and reuse the same record builder as other routes."""
        loaded = self.folder_picker.get_eml_from_folder()
        if loaded is None:
            return None
        sender, message = loaded
        return self.build_record_from_message(message, channel="email", sender=sender)

    def ask_yes_no(self, question):
        """Prompt until yes/y or no/n is entered, ignoring case and surrounding spaces.

        Return a boolean; leave cancellation handling to the application loop.
        """
        answer = self._terminal.read(question).strip().lower()

        while answer not in ("y", "yes", "n", "no"):
            answer = self._terminal.read("Please type yes/y or no/n: ").strip().lower()

        return answer in ("y", "yes")

    def collect_feedback(self) -> dict | None:
        """Ask whether to leave a correction, then collect it."""
        if not self.ask_yes_no(
            "Would you like to leave feedback about this assessment? (yes/no): "
        ):
            return None
        return self.collect_correction()

    def collect_correction(self) -> dict:
        """Collect one correction for the newest saved assessment."""
        categories = {
            "1": "false_positive",
            "2": "false_negative",
            "3": "incorrect_priority",
            "4": "incorrect_explanation",
            "5": "application_bug",
            "6": "usability_issue",
            "7": "other",
        }
        self._terminal.write("1. False positive (this looks safe)")
        self._terminal.write("2. False negative (this looks suspicious)")
        self._terminal.write("3. Incorrect priority")
        self._terminal.write("4. Incorrect explanation")
        self._terminal.write("5. Application bug")
        self._terminal.write("6. Usability issue")
        self._terminal.write("7. Other")
        choice = self.get_valid_choice(
            "Choose a feedback category (1-7): ",
            tuple(categories),
            "Invalid category. Please choose 1-7: ",
        )
        category = categories[choice]
        corrected_priority = None
        if category == "incorrect_priority":
            corrected_priority = self.get_valid_choice(
                "What should the priority be (high/medium/low)? ",
                ("high", "medium", "low"),
                "Please choose high, medium, or low: ",
            ).upper()

        comment = self._terminal.read("Additional details (press Enter to skip): ")
        while len(comment) > 2000:
            comment = self._terminal.read(
                "Details must be at most 2000 characters. Please try again: "
            )
        return {
            "category": category,
            "comment": comment or None,
            "corrected_priority": corrected_priority,
        }

    def collect_exposure(self) -> dict | None:
        """Offer the optional post-verdict checklist, or None when skipped.

        A POSIX TTY gets the interactive checkbox screen. Pipes, CI and tests
        get a numbered prompt through the terminal so line-based input still
        works. Both paths map to the same stored exposure fields.
        """
        stdin = self._stdin if self._stdin is not None else sys.stdin
        if stdin.isatty() and tty_supported():
            stdout = self._stdout if self._stdout is not None else sys.stdout
            selection = ExposureScreen(stdin, stdout).run()
        else:
            selection = self._read_numbered_exposure()
        return build_exposure(selection)

    def _read_numbered_exposure(self) -> tuple[str, ...] | None:
        """Read comma-separated numbers until valid; blank means skip."""
        self._terminal.write(NUMBERED_HEADING)
        answer = self._terminal.read(NUMBERED_PROMPT)
        while True:
            try:
                return parse_numbered_selection(answer)
            except ValueError:
                answer = self._terminal.read(
                    "Invalid answer. Enter numbers like 1,3,4 + Enter, "
                    "or Enter to skip: "
                )

    def get_message(self):
        """Collect a multi-line message until END is entered on its own line."""
        self._terminal.write(
            "Paste your message. Type END on its own line to finish."
        )

        while True:
            lines = []

            while True:
                line = self._terminal.read(
                    "Enter the suspicious message: " if not lines else ""
                )

                if line == "END":
                    break

                lines.append(line)

            message = "\n".join(lines)

            if message.strip():
                return message

            self._terminal.write(
                "Message cannot be blank. Please enter the suspicious message."
            )

    def display_result(self, result: dict | None) -> None:
        """Display a validated outcome or an explicit unavailable assessment."""
        self._presenter.display_result(result)

    def display_record(self, record: dict) -> None:
        """Display a validated saved record, preserving absent historical fields."""
        self._presenter.display_record(record)

    def collect_summary_filter(self) -> dict:
        """Ask which priority and channel to include; Enter keeps every report."""
        priority = self.get_valid_choice(
            "Priority to include (high, medium, low, or Enter for all): ",
            ("", "high", "medium", "low"),
            "Please enter high, medium, low, or press Enter: ",
        )
        channel = self.get_valid_choice(
            "Channel to include (email, sms, chat, or Enter for all): ",
            ("", "email", "sms", "chat"),
            "Please enter email, sms, chat, or press Enter: ",
        )
        return {"priority": priority or None, "channel": channel or None}

    def collect_csv_path(self) -> str | None:
        """Read a new CSV destination, or cancel on an empty response."""
        return self._terminal.read("Path for new CSV file (Enter to skip): ").strip() or None

    def display_summary(self, summary, description: str = "all reports") -> None:
        """Display a report summary for the given filter description."""
        self._presenter.display_summary(summary, description)

    def display_list(self, records: list[dict]) -> None:
        """Display validated saved summaries without altering or reassessing outcomes."""
        self._presenter.display_list(records)

    def show_message(self, text) -> None:
        """Print an application-supplied status or error message to the terminal."""
        self._terminal.write(text)
