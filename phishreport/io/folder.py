"""Choose and read an email from a local folder."""

from pathlib import Path

from phishreport import local_settings

from .eml import EmlReader
from .terminal import Terminal

EML_FOLDER_KEY = "eml_folder"
EML_PAGE_SIZE = 5


def _is_email_folder(folder: object) -> bool:
    """Check external preference/input values before constructing a filesystem path."""
    if not isinstance(folder, str) or not folder.strip():
        return False
    try:
        return Path(folder).is_dir()
    except (OSError, ValueError):
        return False


class EmlFolderPicker:
    """Manage the email folder preference and paginated file selection."""

    def __init__(self, terminal: Terminal, reader: EmlReader):
        self._terminal = terminal
        self._reader = reader

    def get_eml_folder(self) -> str:
        """Return a usable saved folder or prompt for one and try to save it."""
        folder = local_settings.get_setting(EML_FOLDER_KEY)
        if _is_email_folder(folder):
            return folder

        if folder:
            self._terminal.write("Saved email folder is invalid or no longer available.")
        self._terminal.write("First time: tell PhishReport which folder holds your .eml files.")
        while True:
            entered = self._terminal.read("Enter the path to your email folder: ")
            entered = entered.strip().strip('"')
            if not entered:
                self._terminal.write("Folder path cannot be blank.")
                continue
            if not _is_email_folder(entered):
                self._terminal.write(
                    "That folder does not exist. Please enter a valid folder path."
                )
                continue
            if local_settings.save_setting(EML_FOLDER_KEY, entered):
                self._terminal.write(
                    "Saved. You won't be asked again while this folder remains available."
                )
            else:
                self._terminal.write(
                    "Could not save the folder preference; using it for this selection only."
                )
            return entered

    @staticmethod
    def list_eml_files(folder: str | Path) -> list[Path]:
        """Return the folder's .eml files, newest first by modified time."""
        files = [p for p in Path(folder).iterdir() if p.is_file() and p.suffix.lower() == ".eml"]
        files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        return files

    def choose_eml_file(self, folder: str | Path) -> Path | None:
        """Show files in pages and allow selection from any page already shown."""
        files = self.list_eml_files(folder)
        if not files:
            self._terminal.write(f"No .eml files found in '{folder}'.")
            return None

        shown = 0
        while True:
            page = files[shown : shown + EML_PAGE_SIZE]
            for index, path in enumerate(page, start=shown + 1):
                self._terminal.write(f"{index}. {path.name}")
            shown += len(page)

            options = "Enter a number to pick a file"
            if shown < len(files):
                options += ", 'm' for more"
            options += ", or 'c' to cancel: "
            answer = self._terminal.read(options).strip().lower()

            if answer == "c":
                return None
            if answer == "m" and shown < len(files):
                continue
            selected = 0
            if answer.isdigit():
                try:
                    selected = int(answer)
                except ValueError:
                    # Some Unicode digits and excessive-length numbers cannot be parsed.
                    pass
            if 1 <= selected <= shown:
                return files[selected - 1]
            self._terminal.write("Invalid choice. Please try again.")

    def get_eml_from_folder(self) -> tuple[str | None, str] | None:
        """Return a decoded email, retry unreadable files, and report listing errors."""
        folder = self.get_eml_folder()
        while True:
            try:
                chosen = self.choose_eml_file(folder)
            except OSError:
                self._terminal.write(
                    "Unable to list the email folder. Check its availability and permissions."
                )
                return None
            if chosen is None:
                return None
            try:
                sender, message = self._reader.read_path(str(chosen))
            except (OSError, ValueError):
                self._terminal.write("Unable to read that email file. Please choose another.")
                self._terminal.write(
                    "Use a valid plain-text or HTML email. Images and attachments are not analysed."
                )
                continue
            self._terminal.write("Email loaded successfully.")
            return sender, message
