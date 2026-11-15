"""User-facing wording selected from trusted AI failure metadata."""

from phishreport.errors import AIUnavailable, AssessmentError

from ._provider_errors import ProviderFailure, ProviderFailureReason


class AIErrorTranslator:
    """Return safe guidance without inspecting arbitrary exception text."""

    def translate(self, error) -> str:
        if isinstance(error, AIUnavailable) and isinstance(error.__cause__, ProviderFailure):
            error = error.__cause__
        if isinstance(error, AssessmentError):
            return error.user_message
        if isinstance(error, ProviderFailure):
            if error.reason in (ProviderFailureReason.TIMEOUT, ProviderFailureReason.TRANSPORT):
                return (
                    "The check failed: could not reach the AI service. "
                    "Check your internet connection and try again."
                )
            if error.reason is ProviderFailureReason.HTTP:
                if 500 <= error.status_code <= 599:
                    return (
                        "The check failed: the AI service is temporarily unavailable. "
                        "Try again shortly."
                    )
                if error.status_code == 429:
                    return (
                        "The check failed: the AI service is busy (rate limited). "
                        "Try again shortly."
                    )
        return "The check failed: the AI could not complete the assessment. Please try again."
