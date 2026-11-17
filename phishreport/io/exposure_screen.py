"""Optional post-verdict checklist for what the user did with a message.

The screen is only offered after the plain assessment is saved, so skipping it
leaves the stored result untouched. Keys are read in raw mode so arrow keys,
Space and Escape work without a line editor; every exit path restores the
terminal, including Ctrl-C.
"""

import os
import re
import select
import sys

try:
    import termios
    import tty
except ImportError:  # pragma: no cover - Windows has no POSIX terminal API
    termios = None
    tty = None

EXPOSURE_HEADING = (
    "Anything you did with it?  (Space toggles, Enter confirms, Esc skips)"
)
EXPOSURE_CHOICES = (
    ("clicked", "Clicked the link"),
    ("downloaded", "Downloaded the file"),
    ("password", "Entered a password"),
    ("otp", "Entered a one-time code"),
)
EXPOSURE_KEYS = tuple(key for key, _ in EXPOSURE_CHOICES)
EXPOSURE_LABELS = dict(EXPOSURE_CHOICES)

NUMBERED_HEADING = (
    "Anything you did with it? 1 clicked, 2 downloaded, 3 password, "
    "4 one-time code"
)
NUMBERED_PROMPT = "Enter numbers like 1,3,4 + Enter, or Enter to skip: "
NUMBERED_KEYS = {"1": "clicked", "2": "downloaded", "3": "password", "4": "otp"}

# A lone Escape arrives as one byte; a short wait distinguishes it from an
# arrow-key sequence such as ESC [ B.
ESCAPE_SEQUENCE_TIMEOUT_SECONDS = 0.05
CTRL_C = "\x03"


def tty_supported() -> bool:
    """Return whether this platform exposes the POSIX terminal controls."""
    return termios is not None and tty is not None and hasattr(os, "read")


def parse_numbered_selection(answer: str) -> tuple[str, ...] | None:
    """Map ``1,3,4``-style input to choice keys; blank means skip."""
    tokens = [token for token in re.split(r"[,\s]+", answer.strip()) if token]
    if not tokens:
        return None
    selection = []
    for token in tokens:
        key = NUMBERED_KEYS.get(token)
        if key is None:
            raise ValueError("Invalid exposure selection.")
        if key not in selection:
            selection.append(key)
    return tuple(selection)


def build_exposure(selection) -> dict | None:
    """Map selected choice keys to the stored exposure fields."""
    chosen = set(selection or ())
    if not chosen:
        return None

    submitted_category = None
    if chosen.intersection({"password", "otp"}):
        # The stored schema has a single submitted_category field, so both
        # choices cannot be kept. Record password when both were entered: it
        # is the broader disclosure and the disclosure rule treats both the
        # same, so the stored score is identical either way.
        submitted_category = "password" if "password" in chosen else "otp"
    return {
        "clicked": "clicked" in chosen,
        "downloaded": "downloaded" in chosen,
        "submitted_category": submitted_category,
        "disclosure_answered": True,
    }


class ExposureScreen:
    """Draw and operate the optional checkbox checklist on a POSIX terminal."""

    def __init__(self, stdin=None, stdout=None) -> None:
        self._stdin = sys.stdin if stdin is None else stdin
        self._stdout = sys.stdout if stdout is None else stdout

    def run(self) -> tuple[str, ...]:
        """Return the chosen keys in screen order; empty means skip."""
        if not tty_supported():
            raise RuntimeError("Interactive exposure input is unavailable.")
        descriptor = self._stdin.fileno()
        original = termios.tcgetattr(descriptor)
        selected = set()
        # Start above the list so the first Down key highlights the first item.
        cursor = -1
        drawn = False
        try:
            tty.setraw(descriptor)
            self._draw(selected, cursor)
            drawn = True
            while True:
                key = self._read_key(descriptor)
                if key == "up":
                    cursor = len(EXPOSURE_KEYS) - 1 if cursor < 0 else (
                        cursor - 1
                    ) % len(EXPOSURE_KEYS)
                elif key == "down":
                    cursor = 0 if cursor < 0 else (cursor + 1) % len(EXPOSURE_KEYS)
                elif key == "space" and cursor >= 0:
                    choice = EXPOSURE_KEYS[cursor]
                    if choice in selected:
                        selected.remove(choice)
                    else:
                        selected.add(choice)
                elif key == "enter":
                    return tuple(key for key in EXPOSURE_KEYS if key in selected)
                elif key == "esc":
                    return ()
                self._redraw(selected, cursor)
        finally:
            if drawn:
                self._clear()
            # Flush any unread keys while restoring: pending input would make
            # the driver set PENDIN instead of returning to the exact settings.
            termios.tcsetattr(descriptor, termios.TCSAFLUSH, original)

    def _read_key(self, descriptor: int) -> str:
        data = os.read(descriptor, 1)
        if not data:
            return "esc"
        character = data.decode("ascii", "ignore")
        if character in ("\r", "\n"):
            return "enter"
        if character == " ":
            return "space"
        if character == CTRL_C:
            raise KeyboardInterrupt
        if character != "\x1b":
            return "other"
        if not select.select(
            [descriptor], [], [], ESCAPE_SEQUENCE_TIMEOUT_SECONDS,
        )[0]:
            return "esc"
        if os.read(descriptor, 1) not in (b"[", b"O"):
            return "esc"
        code = os.read(descriptor, 1)
        return {b"A": "up", b"B": "down"}.get(code, "other")

    def _row(self, index: int, selected: set, cursor: int) -> str:
        mark = "x" if EXPOSURE_KEYS[index] in selected else " "
        row = f"  [{mark}] {EXPOSURE_LABELS[EXPOSURE_KEYS[index]]}"
        if index == cursor:
            # Reverse video marks the cursor without changing the visible text.
            return f"\x1b[7m{row}\x1b[0m"
        return row

    def _draw(self, selected: set, cursor: int) -> None:
        lines = [EXPOSURE_HEADING]
        lines += [self._row(index, selected, cursor) for index in range(len(EXPOSURE_KEYS))]
        self._write("".join(f"\r{line}\n" for line in lines))

    def _redraw(self, selected: set, cursor: int) -> None:
        rows = [
            self._row(index, selected, cursor) for index in range(len(EXPOSURE_KEYS))
        ]
        self._write(
            f"\x1b[{len(rows)}A"
            + "".join(f"\r\x1b[2K{row}\n" for row in rows)
        )

    def _clear(self) -> None:
        self._write(f"\x1b[{len(EXPOSURE_KEYS) + 1}A\r\x1b[J")

    def _write(self, text: str) -> None:
        self._stdout.write(text)
        self._stdout.flush()
