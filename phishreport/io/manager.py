"""Coordinate the CLI menu, input routes, and report presentation."""

from .eml import EmlReader
from .folder import EmlFolderPicker
from .presenter import ReportPresenter
from .terminal import Terminal

UPLOAD_TYPE_MESSAGE = (
    "Only .eml email files are supported. Images and attachments are not analysed."
)


class IOManager:
    """Collect incident records and display reports through a shared terminal."""

    def __init__(self, terminal: Terminal) -> None:
        self._terminal = terminal
        self.eml_reader = EmlReader()
        self.folder_picker = EmlFolderPicker(terminal, self.eml_reader)
        self._presenter = ReportPresenter(terminal)

    def main_menu(self) -> str:
        """Display the CLI menu and return a validated, normalized menu choice."""
        self._terminal.write("\n=== PhishReport ===")
        self._terminal.write("1. Check a new message (Manual Input)")
        self._terminal.write("2. Import an email (.eml file)")
        self._terminal.write("3. Upload an email (.eml file)")
        self._terminal.write("4. View saved reports")
        self._terminal.write("5. Summarize saved reports")
        self._terminal.write("6. Quit")

        return self.get_valid_choice(
            "Choose 1-6: ",
            ("1", "2", "3", "4", "5", "6"),
            "Invalid choice. Please choose 1-6: ",
        )

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
        """Collect validated manual fields, then use the shared exposure questions."""
        channel = self.get_channel()
        sender = self.get_sender()
        message = self.get_message()
        return self.build_record_from_message(message, channel=channel, sender=sender)

    def build_record_from_message(
        self, message: str, channel: str = "email", sender: str | None = None
    ) -> dict:
        """Build a record from already-obtained message text (e.g. an uploaded file).

        Manual, folder and upload collection all use this single action/record contract.
        The caller supplies message text validated by its collection or decoding path.
        """
        has_link, link = self.get_link_information()
        has_file, file_name = self.get_file_information()
        user_actions = self.collect_user_actions(has_link, has_file)
        return {
            "channel": channel,
            "sender": sender,
            "message": message,
            "has_link": has_link,
            "link": link,
            "has_file": has_file,
            "file_name": file_name,
            "clicked": user_actions["clicked"],
            "downloaded": user_actions["downloaded"],
            "submitted_category": user_actions["submitted_category"],
        }

    def collect_input_from_upload(self, upload) -> dict:
        """Use the folder import's MIME parser and exposure contract for browser EML."""
        if not upload["filename"].lower().endswith(".eml"):
            raise ValueError(UPLOAD_TYPE_MESSAGE)
        sender, message = self.eml_reader.read_bytes(upload["content"])
        return self.build_record_from_message(message, sender=sender)

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
        return self.build_record_from_message(message, sender=sender)

    def ask_yes_no(self, question):
        """Prompt until yes/y or no/n is entered, ignoring case and surrounding spaces.

        Return a boolean; leave cancellation handling to the application loop.
        """
        answer = self._terminal.read(question).strip().lower()

        while answer not in ("y", "yes", "n", "no"):
            answer = self._terminal.read("Please type yes/y or no/n: ").strip().lower()

        return answer in ("y", "yes")

    def collect_feedback(self) -> dict | None:
        """Collect one optional correction about the assessment just displayed."""
        if not self.ask_yes_no(
            "Would you like to leave feedback about this assessment? (yes/no): "
        ):
            return None

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

    def get_channel(self):
        """Return the user-selected channel: email, sms or chat."""
        return self.get_valid_choice(
            "Enter channel (Email/SMS/Chat): ",
            ("email", "sms", "chat"),
            "Invalid channel. Please enter Email, SMS, or Chat: ",
        )

    def get_sender(self):
        """Return stripped sender text, or None for a blank answer; do not verify identity."""
        sender = self._terminal.read("Enter sender information (press Enter if unknown): ").strip()

        if sender == "":
            return None

        return sender

    def get_message(self):
        """Prompt for a single nonblank line and return its stripped message text."""
        message = self._terminal.read("Enter the suspicious message: ").strip()

        while message == "":
            message = self._terminal.read(
                "Message cannot be blank. Please enter the suspicious message: "
            ).strip()

        return message

    def get_link_information(self):
        """Return (has_link, link), requiring nonblank text when a link is reported.

        Return (False, None) when absent. Collect the supplied text without
        visiting the link or validating its destination.
        """
        has_link = self.ask_yes_no("Was a link included? (yes/no): ")

        if not has_link:
            return False, None

        link = self._terminal.read("Enter the link: ").strip()

        while link == "":
            link = self._terminal.read("Link cannot be blank. Please enter the link: ").strip()

        return True, link

    def get_file_information(self):
        """Return (has_file, file_name), requiring a name when a file is reported.

        Return (False, None) when absent. This question collects metadata only;
        it does not open or inspect the named file.
        """
        has_file = self.ask_yes_no("Was a file included? (yes/no): ")

        if not has_file:
            return False, None

        file_name = self._terminal.read("Enter the file name: ").strip()

        while file_name == "":
            file_name = self._terminal.read(
                "File name cannot be blank. Please enter the file name: "
            ).strip()

        return True, file_name

    def get_submitted_category(self):
        """Return password, otp or None from the validated disclosure answer."""
        submitted = self.get_valid_choice(
            "Did you give a password or code? (password/otp/no): ",
            ("password", "otp", "no"),
            "Please type password, otp or no: ",
        )

        if submitted == "no":
            return None

        return submitted

    def collect_user_actions(self, has_link, has_file):
        """Return clicked, downloaded and submitted_category from exposure questions.

        Ask about clicks/downloads only when the corresponding item was reported;
        otherwise record False. Always ask whether credentials were submitted.
        """
        if has_link:
            clicked = self.ask_yes_no("Did you click the link? (yes/no): ")
        else:
            clicked = False

        if has_file:
            downloaded = self.ask_yes_no("Did you download the file? (yes/no): ")
        else:
            downloaded = False

        submitted_category = self.get_submitted_category()

        return {
            "clicked": clicked,
            "downloaded": downloaded,
            "submitted_category": submitted_category,
        }

    def display_result(self, result: dict | None) -> None:
        """Display a validated outcome or an explicit unavailable assessment."""
        self._presenter.display_result(result)

    def display_record(self, record: dict) -> None:
        """Display a validated saved record, preserving absent historical fields."""
        self._presenter.display_record(record)

    def collect_summary_filter(self) -> dict:
        """Ask which priority and channel to summarize; Enter keeps every report."""
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

    def display_summary(self, summary, description: str = "all reports") -> None:
        """Display a report summary for the given filter description."""
        self._presenter.display_summary(summary, description)

    def display_list(self, records: list[dict]) -> None:
        """Display validated saved summaries without altering or reassessing outcomes."""
        self._presenter.display_list(records)

    def show_message(self, text) -> None:
        """Print an application-supplied status or error message to the terminal."""
        self._terminal.write(text)
