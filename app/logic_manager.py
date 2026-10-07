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


