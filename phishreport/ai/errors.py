"""User-facing wording for AI service failures."""


class AIErrorTranslator:
    """Turn an AI RuntimeError into a short, actionable message for the user.

    Keeps the word 'failed' so the reason is clear, and adds guidance based on
    the kind of failure (offline, service error, rate limit).
    """

    def translate(self, error) -> str:
        text = str(error).lower()
        if "timed out" in text or "could not complete" in text:
            return (
                "The check failed: could not reach the AI service. "
                "Check your internet connection and try again."
            )
        if "http 5" in text:
            return "The check failed: the AI service is temporarily unavailable. Try again shortly."
        if "http 429" in text:
            return "The check failed: the AI service is busy (rate limited). Try again shortly."
        return "The check failed: the AI could not complete the assessment. Please try again."
