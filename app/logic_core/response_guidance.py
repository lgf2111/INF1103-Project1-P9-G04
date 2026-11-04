"""Build user-facing reasons and response steps from an assessment."""


class ResponseGuidanceBuilder:
    """Create exposure-aware explanations and checklists for an assessment."""

    def build(self, record, score, priority):
        """Return reasons and actions while leaving the source record unchanged."""
        findings = record["ai"]
        category = record["submitted_category"]
        reasons = []

        if category == "password":
            reasons.append("You reported sharing a password.")
        elif category == "otp":
            reasons.append("You reported sharing a one-time code.")
        if record["clicked"]:
            reasons.append("You reported clicking a link.")
        if record["downloaded"]:
            reasons.append("You reported downloading a file.")
        if findings["suspicious"]:
            reasons.append("The AI identified suspicious indicators in the supplied content.")
        if findings["credential_request"]:
            reasons.append(
                "The AI identified a request for login credentials or a verification code."
            )
        if findings["insufficient_context"]:
            reasons.append(
                "The AI reported insufficient context; this assessment is limited."
            )
        if not reasons:
            reasons.append("The AI reported no suspicious indicators in the supplied content.")

        if priority == "HIGH":
            checklist = [
                "Stop further interaction with the message.",
                "Verify the request through an independently obtained official channel.",
                "Report the message and your actions to your security team "
                "or the relevant service.",
            ]
        elif priority == "MEDIUM":
            checklist = [
                "Avoid further interaction until you verify the request independently.",
                "Do not submit passwords or one-time codes through the message.",
                "Report the message if it appears suspicious.",
            ]
        else:
            checklist = [
                "Remain cautious.",
                "Verify unusual requests independently.",
                "Report the message if additional warning signs appear.",
            ]

        if category == "password":
            checklist.insert(
                0,
                "Change the affected password through the official app or website.",
            )
        elif category == "otp":
            checklist.insert(
                0,
                "Contact the relevant service through an official channel "
                "about the shared one-time code.",
            )
        if record["clicked"]:
            checklist.append("Close the message link and avoid visiting it again.")
        if record["downloaded"]:
            checklist.append(
                "Do not open or run the downloaded file; if already opened, "
                "contact your security team."
            )

        return {
            "priority": priority,
            "score": score,
            "checklist": checklist,
            "reasons": reasons,
        }
