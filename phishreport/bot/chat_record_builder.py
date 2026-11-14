"""Build incident records from text sent to the chat bot."""

import re


class ChatRecordBuilder:
    """Turn chat message text into the record the managers expect."""

    def build(self, text: str, sender: str | None = None) -> dict:
        # These are textual clues, not verified links/attachments or user actions.
        # Keep source order and spelling; never fetch a URL or infer exposure.
        emails = list(re.finditer(r"[\w.+%-]+@[\w.-]+", text))
        urls = [
            match
            for match in re.finditer(r"(?<![\w@])(?:https?://|www\.)[^\s<>\"']+", text, re.I)
            if not any(email.start() <= match.start() < email.end() for email in emails)
        ]
        link = None
        if urls:
            link = urls[0].group()
            extra_closing = {
                closing: link.count(closing) - link.count(opening)
                for opening, closing in (("(", ")"), ("[", "]"), ("{", "}"))
            }
            while link:
                if link[-1] in ".,;:!?":
                    link = link[:-1]
                elif extra_closing.get(link[-1], 0) > 0:
                    extra_closing[link[-1]] -= 1
                    link = link[:-1]
                else:
                    break

        # Ignore filenames embedded in email addresses and URLs, including paths
        # and queries: a URL alone does not establish a file attachment.
        excluded_spans = [match.span() for match in urls]
        excluded_spans += [match.span() for match in emails]
        filename = None
        for match in re.finditer(
            r"(?<![\w.-])[\w-][\w.-]*\.(?:pdf|docx?|xlsx?|zip|apk|exe|jpe?g|png|gif|webp)"
            r"(?!\w|\.\w)",
            text,
            re.I,
        ):
            if not any(
                start < match.end() and match.start() < end for start, end in excluded_spans
            ):
                filename = match.group()
                break
        attachment_mentioned = bool(re.search(
            r"\b(?:attachments?|attached\s+(?:(?:a|an|the)\s+)?(?:files?|documents?))\b",
            text,
            re.I,
        ))
        return {
            "channel": "chat",
            "sender": sender,
            "message": text,
            "has_link": link is not None,
            "link": link,
            "has_file": filename is not None or attachment_mentioned,
            "file_name": filename,
            "clicked": False,
            "downloaded": False,
            "submitted_category": None,
        }
