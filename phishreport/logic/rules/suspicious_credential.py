"""Rule for suspicious content that requests credentials."""

from .base import PriorityRule


class SuspiciousCredentialRule(PriorityRule):
    """Score the combined suspicious-content and credential-request finding."""

    def matches(self, record):
        findings = record["ai"]
        return findings["suspicious"] and findings["credential_request"]

    def score(self, record):
        return 60
