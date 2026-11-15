"""Render assessment documents as the Gmail phishing-alert HTML body."""

from .assessment_document import AssessmentDocument
from .document_renderer import DocumentRenderer, RenderContext


class HTMLAlertRenderer(DocumentRenderer):
    """Build Telegram HTML markup from adapter-prepared document values.

    Dynamic document values and context must already be escaped by the Telegram
    adapter. This renderer adds only the alert's static HTML structure.
    """

    BADGES = {"HIGH": "🚨 <b>HIGH risk</b>", "MEDIUM": "⚠️ <b>MEDIUM risk</b>"}

    def render(
        self,
        document: AssessmentDocument,
        context: RenderContext | None = None,
    ) -> str:
        context = context or {}
        assessment_fields = {}
        trace_entries = ()
        reason_entries = ()
        action_entries = ()
        for kind, _title, entries in document.sections:
            if kind == "fields":
                assessment_fields = dict(entries)
            elif kind == "trace":
                trace_entries = entries
            elif kind == "bullets":
                reason_entries = entries
            elif kind == "numbered":
                action_entries = entries

        priority = assessment_fields.get("Priority", "") or ""
        badge = self.BADGES.get(
            str(priority).upper(), "⚠️ <b>Possible phishing</b>"
        )
        sender = context.get("sender") or "Unknown sender"
        subject = context.get("subject") or ""
        source_url = context.get("source_url")

        lines = [
            f"{badge} · possible phishing email",
            "",
            f"<b>From:</b> {sender}",
        ]
        if subject:
            lines.append(f"<b>Subject:</b> {subject}")

        score = assessment_fields.get("Rule-based score")
        lines.append(f"<b>Score:</b> {score if score is not None else 'n/a'}/100")

        matched_rule = assessment_fields.get("Matched rule")
        if matched_rule:
            lines.append(f"<b>Matched rule:</b> {matched_rule}")

        if trace_entries:
            lines += ["", "<b>Rule evaluation trace</b>"]
            for label, value in trace_entries:
                matched, score = value
                status = "matched" if matched else "not matched"
                score_text = f" (score: {score})" if score is not None else ""
                lines.append(f"• {label}: {status}{score_text}")

        if reason_entries:
            lines += ["", "<b>Why it was flagged</b>"]
            lines += [f"• {value}" for _, value in reason_entries]

        if action_entries:
            lines += ["", "<b>What to do</b>"]
            lines += [
                f"{number}. {value}"
                for number, (_, value) in enumerate(action_entries, start=1)
            ]

        if source_url:
            lines += ["", f'📧 <a href="{source_url}">Open the email in Gmail</a>']
        lines += ["", "<i>Do not click links or reply. A low score never guarantees safety.</i>"]
        return "\n".join(lines)
