# logic_manager.py
# Holds extracted details for the AI-to-Logic-to-AI flow
# and computes deterministic logic results for display.

def hold_details(details):
    """
    Validate extracted contact details and return them unchanged.

    This must remain compatible with ai_manager.response_prompt(details),
    which expects exactly:
    {
        "emails": [...],
        "phone_numbers": [...],
        "ip_addresses": [...]
    }
    """
    required_keys = {
        "emails",
        "phone_numbers",
        "ip_addresses",
    }

    if not isinstance(details, dict):
        raise ValueError("Details must be a dictionary.")

    if set(details) != required_keys:
        raise ValueError(
            "Details must contain exactly: "
            + ", ".join(sorted(required_keys))
        )

    for key in required_keys:
        if not isinstance(details[key], list):
            raise ValueError(f"{key} must be a list.")

        for value in details[key]:
            if not isinstance(value, str):
                raise ValueError(f"Each value in {key} must be a string.")

    return details

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


def evaluate(record, details):
    """
    Evaluate the full user record and extracted details.

    Returns:
        {
            "priority": "LOW" | "MEDIUM" | "HIGH",
            "score": int,
            "checklist": [str, ...]
        }
    """
    _validate_record(record)
    hold_details(details)

    score = 0
    reasons = []

    if record.get("has_link") is True:
        score += 10
        reasons.append("The message included a link.")

    if record.get("clicked") is True:
        score += 20
        reasons.append("The user clicked the link.")

    if record.get("has_file") is True:
        score += 15
        reasons.append("The message included a file.")

    if record.get("downloaded") is True:
        score += 25
        reasons.append("The user downloaded the file.")

    if record.get("submitted_category") == "password":
        score += 40
        reasons.append("The user submitted a password.")

    elif record.get("submitted_category") == "otp":
        score += 35
        reasons.append("The user submitted an OTP.")

    if not record.get("sender"):
        score += 5
        reasons.append("Sender information was not available.")

    if details.get("emails"):
        score += 5
        reasons.append("The message contains an email address.")

    if details.get("phone_numbers"):
        score += 5
        reasons.append("The message contains a phone number.")

    if details.get("ip_addresses"):
        score += 10
        reasons.append("The message contains an IP address.")

    # Cap the score at 100 no matter how many factors apply.
    score = min(score, 100)

    if score >= 70:
        priority = "HIGH"
        checklist = [
            "Stop all contact with the sender.",
            "Do not click links or open files from this message.",
            "Change any affected passwords immediately.",
            "Report the message to your supervisor or security team.",
            "Monitor your accounts for suspicious activity.",
        ]
    elif score >= 35:
        priority = "MEDIUM"
        checklist = [
            "Avoid further interaction with the message.",
            "Verify the sender through an official channel.",
            "Do not submit passwords or OTPs.",
            "Report the message if it appears suspicious.",
        ]
    else:
        priority = "LOW"
        checklist = [
            "Remain cautious.",
            "Verify unusual requests independently.",
            "Report the message if additional warning signs appear.",
        ]

    return {
        "priority": priority,
        "score": score,
        "checklist": checklist,
        "reasons": reasons,
    }

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
