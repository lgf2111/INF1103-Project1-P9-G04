"""Structured provider failures with controlled, safe exception messages."""

from enum import Enum


class ProviderFailureReason(Enum):
    """Supported reasons for an AI provider failure."""

    CONFIGURATION = "configuration"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    HTTP = "http"
    INVALID_RESPONSE = "invalid_response"


class ProviderFailure(RuntimeError):
    """Carry a validated reason and optional HTTP status without provider text."""

    def __init__(
        self,
        reason: ProviderFailureReason,
        *,
        status_code: int | None = None,
    ) -> None:
        if not isinstance(reason, ProviderFailureReason):
            raise TypeError("reason must be a ProviderFailureReason.")
        if status_code is not None and type(status_code) is not int:
            raise TypeError("status_code must be an integer.")
        if reason is ProviderFailureReason.HTTP:
            if status_code is None or not 100 <= status_code <= 599:
                raise ValueError("HTTP failures require a status_code from 100 to 599.")
            message = f"AI provider returned HTTP {status_code}."
        else:
            if status_code is not None:
                raise ValueError("status_code is only valid for HTTP failures.")
            message = {
                ProviderFailureReason.CONFIGURATION: "AI provider configuration is invalid.",
                ProviderFailureReason.TIMEOUT: "The AI request timed out.",
                ProviderFailureReason.TRANSPORT: "Could not complete the AI request.",
                ProviderFailureReason.INVALID_RESPONSE: "AI provider returned an invalid response.",
            }[reason]

        self.reason = reason
        self.status_code = status_code
        super().__init__(message)
