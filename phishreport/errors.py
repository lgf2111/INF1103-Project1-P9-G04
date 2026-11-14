"""Application failures with safe messages for user-facing boundaries."""


class AssessmentError(Exception):
    """Base failure exposing a safe default message without diagnostic details."""

    user_message = "The assessment could not be completed. Please try again."

    def __init__(self) -> None:
        super().__init__(self.user_message)


class AIUnavailable(AssessmentError):
    """The AI service could not complete an assessment."""

    user_message = "AI could not complete the assessment. Please try again."


class InvalidInput(AssessmentError):
    """The supplied assessment input cannot be processed."""

    user_message = "Invalid input. Please revise it and try again."


class StorageFailure(AssessmentError):
    """Local report history could not be accessed."""

    user_message = "Could not access local report history. Please try again."


class FeedbackRejected(AssessmentError):
    """Submitted feedback could not be accepted."""

    user_message = "Feedback could not be accepted. Please check the details."
