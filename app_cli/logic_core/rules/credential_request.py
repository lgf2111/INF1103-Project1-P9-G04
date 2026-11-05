"""Rule for AI findings that request credentials without suspicious flag."""

from .base import PriorityRule


class CredentialRequestRule(PriorityRule):
    """Apply caution when credentials are requested, even without suspicion."""

    def matches(self, record):
        return record["ai"]["credential_request"]

    def score(self, record):
        return 40
