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


def html_to_text(source, limit, allow_empty=False):
    """Convert HTML source into bounded text without rendering or fetching URLs.

    Retain visible text and selected attribute values; omit ignored sections.
    The limit counts normalized output characters. Raise ValueError if the
    limit is exceeded, or the result is empty unless allow_empty is True.
    """
    state = {"chunks": [], "length": 0, "ignored": [], "pending": ""}
    parser = HTMLParser(convert_charrefs=True)
    # Configure an existing library object; no team-authored class/subclass.
    parser.handle_starttag = lambda tag, attrs: _start(state, tag, attrs, limit)
    parser.handle_startendtag = lambda tag, attrs: _empty(state, tag, attrs, limit)
    parser.handle_endtag = lambda tag: _end(state, tag, limit)
    parser.handle_data = lambda data: _append(state, data, limit) if not state["ignored"] else None
    parser.feed(source)
    parser.close()
    text = "".join(state["chunks"])
    if not text and not allow_empty:
        raise ValueError("Email HTML has no usable text or link targets.")
    return text


def _append(state, text, limit):
    """Append normalized text to shared parser state within the character limit.

    Mutate chunks, length and pending whitespace in place. Raise ValueError
    when output exceeds the limit; callers must abandon that parse on failure.
    """
    # Keep whitespace pending until another word arrives. Leading/trailing
    # formatting and repeated blank lines then never consume the text budget.
    for match in re.finditer(r"\s+|\S+", text):
        token = match.group()
        if token.isspace():
            if any(character in token for character in LINE_BREAKS):
                state["pending"] = "\n"
            elif state["pending"] != "\n":
                state["pending"] = " "
            continue
        separator = state["pending"] if state["chunks"] else ""
        piece = separator + token
        state["length"] += len(piece)
        if state["length"] > limit:
            raise ValueError("Email exceeds the message length limit.")
        state["chunks"].append(piece)
        state["pending"] = ""


def _start(state, tag, attrs, limit):
    """Update parser state for an opening tag and retain relevant attributes.

    Track ignored sections and block spacing. URL values are preserved as
    text without being resolved or fetched; cid: and data: targets are omitted.
    """
    if tag in IGNORED:
        state["ignored"].append(tag)
        return
    if state["ignored"]:
        return
    if tag in BLOCKS:
        _append(state, "\n", limit)
    # Preserve destinations alongside visible labels so the assessment can compare them.
    for name, value in attrs:
        if value and name in ("href", "src", "action"):
            if not value.lower().startswith(("cid:", "data:")):
                _append(state, f" [Target: {value}] ", limit)
        elif value and name in ("alt", "title"):
            _append(state, f" {value} ", limit)


def _end(state, tag, limit):
    """Close an ignored section or add pending block spacing to parser state."""
    if state["ignored"]:
        if tag in state["ignored"]:
            # Close the most recent matching ignored section and its nested sections.
            index = len(state["ignored"]) - 1 - state["ignored"][::-1].index(tag)
            del state["ignored"][index:]
        return
    if tag in BLOCKS:
        _append(state, "\n", limit)


def _empty(state, tag, attrs, limit):
    """Process a self-closing tag through the shared opening and closing rules."""
    _start(state, tag, attrs, limit)
    _end(state, tag, limit)
