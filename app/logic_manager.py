# logic_manager.py
# Computes response priorities and guidance from validated AI findings and reported actions.


def score(record):
    """Return a response-priority score using the first matching rule.

    The caller must supply AI findings validated against the original input.
    Check the fields consumed here without coercing values or mutating the record.
    Contact/link/file presence does not establish phishing. Scores are priorities,
    not calibrated phishing probabilities.
    """
    _validate_record(record)
    findings = record.get("ai")
    if not isinstance(findings, dict):
        raise ValueError("Record must contain validated AI findings.")
    for key in ("credential_request", "suspicious", "insufficient_context"):
        if not isinstance(findings.get(key), bool):
            raise ValueError("AI finding must be true or false: " + key)

    # Reported disclosure takes precedence even if the AI misses the threat.
    if record["submitted_category"] in ("password", "otp"):
        return 90
    if findings["suspicious"] and (record["clicked"] or record["downloaded"]):
        return 80
    if findings["suspicious"] and findings["credential_request"]:
        return 60
    if findings["suspicious"]:
        return 45
    if findings["insufficient_context"]:
        return 35
    return 10


def route(record):
    """Route an assessed record using the logic score and agreed thresholds."""
    value = score(record)
    if value >= 70:
        return "HIGH"
    if value >= 35:
        return "MEDIUM"
    return "LOW"


def evaluate(record):
    """Return score, priority, reasons and exposure-aware guidance for a validated record.

    The caller supplies schema/source-validated AI findings. No API, terminal or
    persistence operations belong here. Preserve the original record unchanged.
    """
    value = score(record)
    priority = route(record)
    findings = record["ai"]
    reasons = []
    category = record["submitted_category"]
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
        reasons.append("The AI identified a request for login credentials or a verification code.")
    if findings["insufficient_context"]:
        reasons.append("The AI reported insufficient context; this assessment is limited.")
    if not reasons:
        reasons.append("The AI reported no suspicious indicators in the supplied content.")

    if priority == "HIGH":
        checklist = [
            "Stop further interaction with the message.",
            "Verify the request through an independently obtained official channel.",
            "Report the message and your actions to your security team or the relevant service.",
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
        checklist.insert(0, "Change the affected password through the official app or website.")
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
            "Do not open or run the downloaded file; if already opened, contact your security team."
        )
    return {"priority": priority, "score": value, "checklist": checklist, "reasons": reasons}

def _validate_record(record):
    """Validate the record shape produced by io_manager.collect_input()."""
    required_keys = {
        "channel",
        "sender",
        "message",
        "has_link",
        "link",
        "has_file",
        "file_name",
        "clicked",
        "downloaded",
        "submitted_category",
    }

    if not isinstance(record, dict):
        raise ValueError("Record must be a dictionary.")

    missing = required_keys - set(record)
    if missing:
        raise ValueError(
            "Record is missing required fields: "
            + ", ".join(sorted(missing))
        )

    if not isinstance(record["channel"], str):
        raise ValueError("channel must be text.")

    if record["sender"] is not None and not isinstance(record["sender"], str):
        raise ValueError("sender must be text or None.")

    if not isinstance(record["message"], str) or not record["message"].strip():
        raise ValueError("message must be non-empty text.")

    for key in ("has_link", "has_file", "clicked", "downloaded"):
        if not isinstance(record[key], bool):
            raise ValueError(f"{key} must be true or false.")

    if record["link"] is not None and not isinstance(record["link"], str):
        raise ValueError("link must be text or None.")

    if record["file_name"] is not None and not isinstance(record["file_name"], str):
        raise ValueError("file_name must be text or None.")

    if record["submitted_category"] not in (None, "password", "otp"):
        raise ValueError(
            "submitted_category must be None, 'password', or 'otp'."
        )
