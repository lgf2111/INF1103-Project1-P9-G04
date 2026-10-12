"""Convert email HTML to bounded source text without rendering or fetching it."""
import re
from html.parser import HTMLParser

BLOCKS = {"br", "p", "div", "li", "tr", "td", "th", "table", "section",
          "article", "h1", "h2", "h3", "h4", "h5", "h6", "hr"}
IGNORED = {"script", "style", "head", "template"}


def html_to_text(source, limit):
    """Preserve body text and URL attributes as inert text, including hidden links."""
    state = {"chunks": [], "length": 0, "ignored": []}
    parser = HTMLParser(convert_charrefs=True)
    # Configure an existing library object; no team-authored class/subclass.
    parser.handle_starttag = lambda tag, attrs: _start(state, tag, attrs, limit)
    parser.handle_startendtag = lambda tag, attrs: _empty(state, tag, attrs, limit)
    parser.handle_endtag = lambda tag: _end(state, tag, limit)
    parser.handle_data = lambda data: _append(state, data, limit) if not state["ignored"] else None
    parser.feed(source)
    parser.close()
    text = "\n".join(
        line for line in (re.sub(r"\s+", " ", line).strip()
                          for line in "".join(state["chunks"]).splitlines()) if line
    )
    if not text:
        raise ValueError("Email HTML has no usable text or link targets.")
    return text


def _append(state, text, limit):
    state["length"] += len(text)
    if state["length"] > limit:
        raise ValueError("Email exceeds the message length limit.")
    state["chunks"].append(text)


def _start(state, tag, attrs, limit):
    if tag in IGNORED:
        state["ignored"].append(tag)
        return
    if state["ignored"]:
        return
    if tag in BLOCKS:
        _append(state, "\n", limit)
    for name, value in attrs:
        if value and name in ("href", "src", "action"):
            if not value.lower().startswith(("cid:", "data:")):
                _append(state, f" [Target: {value}] ", limit)
        elif value and name in ("alt", "title"):
            _append(state, f" {value} ", limit)


def _end(state, tag, limit):
    if state["ignored"]:
        if tag in state["ignored"]:
            index = len(state["ignored"]) - 1 - state["ignored"][::-1].index(tag)
            del state["ignored"][index:]
        return
    if tag in BLOCKS:
        _append(state, "\n", limit)


def _empty(state, tag, attrs, limit):
    _start(state, tag, attrs, limit)
    _end(state, tag, limit)
