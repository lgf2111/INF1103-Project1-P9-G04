"""Convert email HTML to bounded source text without rendering or fetching it."""

import re
from html.parser import HTMLParser

BLOCKS = {
    "br",
    "p",
    "div",
    "li",
    "tr",
    "td",
    "th",
    "table",
    "section",
    "article",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
}
IGNORED = {"script", "style", "head", "template"}
LINE_BREAKS = "\r\n\v\f\x1c\x1d\x1e\x85\u2028\u2029"


class EmailTextExtractor:
    """Convert email HTML into bounded text without rendering or fetching URLs."""

    def __init__(self, limit, allow_empty=False):
        self._limit = limit
        self._allow_empty = allow_empty

    def extract(self, source):
        """Convert HTML source into bounded text without rendering or fetching URLs.

        Retain visible text and selected attribute values; omit ignored sections.
        The limit counts normalized output characters. Raise ValueError if the
        limit is exceeded, or the result is empty unless allow_empty is True.
        """
        text = _EmailHTMLParser(self._limit).extract_text(source)
        if not text and not self._allow_empty:
            raise ValueError("Email HTML has no usable text or link targets.")
        return text


class _EmailHTMLParser(HTMLParser):
    """Collect normalized text and selected attributes from one HTML source."""

    def __init__(self, limit):
        super().__init__(convert_charrefs=True)
        self._limit = limit
        self._chunks = []
        self._length = 0
        self._ignored_tags = []
        self._pending_whitespace = ""

    def extract_text(self, source):
        """Feed and finalize the source before returning the collected text."""
        self.feed(source)
        self.close()
        return "".join(self._chunks)

    def handle_starttag(self, tag, attrs):
        """Track ignored sections and retain relevant attributes."""
        if tag in IGNORED:
            self._ignored_tags.append(tag)
            return
        if self._ignored_tags:
            return
        if tag in BLOCKS:
            self._append("\n")
        # Preserve destinations alongside visible labels for comparison.
        for name, value in attrs:
            if value and name in ("href", "src", "action"):
                if not value.lower().startswith(("cid:", "data:")):
                    self._append(f" [Target: {value}] ")
            elif value and name in ("alt", "title"):
                self._append(f" {value} ")

    def handle_endtag(self, tag):
        """Close an ignored section or add pending block spacing."""
        if self._ignored_tags:
            # Close the most recent matching section and anything nested in it.
            for index in range(len(self._ignored_tags) - 1, -1, -1):
                if self._ignored_tags[index] == tag:
                    del self._ignored_tags[index:]
                    break
            return
        if tag in BLOCKS:
            self._append("\n")

    def handle_data(self, data):
        """Collect text outside ignored sections."""
        if not self._ignored_tags:
            self._append(data)

    def _append(self, text):
        """Append normalized text within the character limit."""
        # Keep whitespace pending until another word arrives. Leading/trailing
        # formatting and repeated blank lines then never consume the text budget.
        for match in re.finditer(r"\s+|\S+", text):
            token = match.group()
            if token.isspace():
                if any(character in token for character in LINE_BREAKS):
                    self._pending_whitespace = "\n"
                elif self._pending_whitespace != "\n":
                    self._pending_whitespace = " "
                continue
            separator = self._pending_whitespace if self._chunks else ""
            piece = separator + token
            self._length += len(piece)
            if self._length > self._limit:
                raise ValueError("Email exceeds the message length limit.")
            self._chunks.append(piece)
            self._pending_whitespace = ""
