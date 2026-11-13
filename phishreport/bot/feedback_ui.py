"""Build compact Telegram keyboards for the assessment correction workflow."""

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

CATEGORY_CODES = {
    "fp": "false_positive",
    "fn": "false_negative",
    "ip": "incorrect_priority",
    "ie": "incorrect_explanation",
    "bug": "application_bug",
    "ux": "usability_issue",
    "other": "other",
}
CATEGORY_LABELS = {
    "fp": "False positive",
    "fn": "False negative",
    "ip": "Incorrect priority",
    "ie": "Incorrect explanation",
    "bug": "Application bug",
    "ux": "Usability issue",
    "other": "Other",
}


def assessment_feedback_keyboard(assessment_id: str) -> InlineKeyboardMarkup:
    """Offer a correction button after a report was saved successfully."""
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton("Suggest a correction", callback_data=f"fb:o:{assessment_id}")]]
    )


def feedback_category_keyboard(assessment_id: str) -> InlineKeyboardMarkup:
    """Ask which part of the assessment the user wants to correct."""
    codes = tuple(CATEGORY_CODES)
    rows = [
        [
            InlineKeyboardButton(
                CATEGORY_LABELS[code], callback_data=f"fb:c:{code}:{assessment_id}"
            )
            for code in codes[offset : offset + 2]
        ]
        for offset in range(0, len(codes), 2)
    ]
    rows.append([InlineKeyboardButton("Cancel", callback_data=f"fb:x:{assessment_id}")])
    return InlineKeyboardMarkup(rows)


def corrected_priority_keyboard(assessment_id: str) -> InlineKeyboardMarkup:
    """Ask for the user's corrected assessment priority."""
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(priority, callback_data=f"fb:p:{priority[0]}:{assessment_id}")
                for priority in ("HIGH", "MEDIUM", "LOW")
            ],
            [InlineKeyboardButton("Cancel", callback_data=f"fb:x:{assessment_id}")],
        ]
    )


def feedback_comment_keyboard(assessment_id: str) -> InlineKeyboardMarkup:
    """Let the user submit without a comment or cancel the correction."""
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Submit without comment", callback_data=f"fb:s:{assessment_id}")],
            [InlineKeyboardButton("Cancel", callback_data=f"fb:x:{assessment_id}")],
        ]
    )
