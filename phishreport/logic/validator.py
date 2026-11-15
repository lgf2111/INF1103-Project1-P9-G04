"""Validation for the records consumed by the Logic Manager."""


class AssessmentValidationError(ValueError):
    """Known invalid record/findings; preserve the lower-level ValueError contract."""


class AssessmentValidator:
    """Validate record fields and the AI findings used by domain rules."""

    _REQUIRED_KEYS = {
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
    _AI_FLAGS = ("credential_request", "suspicious", "insufficient_context")

    def validate_record(self, record):
        """Validate required input fields without coercing or modifying values."""
        if not isinstance(record, dict):
            raise AssessmentValidationError("Record must be a dictionary.")

        missing = self._REQUIRED_KEYS - set(record)
        if missing:
            raise AssessmentValidationError(
                "Record is missing required fields: " + ", ".join(sorted(missing))
            )

        if not isinstance(record["channel"], str):
            raise AssessmentValidationError("channel must be text.")
        if record["sender"] is not None and not isinstance(record["sender"], str):
            raise AssessmentValidationError("sender must be text or None.")
        if not isinstance(record["message"], str) or not record["message"].strip():
            raise AssessmentValidationError("message must be non-empty text.")

        for key in ("has_link", "has_file", "clicked", "downloaded"):
            if not isinstance(record[key], bool):
                raise AssessmentValidationError(f"{key} must be true or false.")

        if record["link"] is not None and not isinstance(record["link"], str):
            raise AssessmentValidationError("link must be text or None.")
        if record["file_name"] is not None and not isinstance(record["file_name"], str):
            raise AssessmentValidationError("file_name must be text or None.")
        if record["submitted_category"] not in (None, "password", "otp"):
            raise AssessmentValidationError(
                "submitted_category must be None, 'password', or 'otp'."
            )

    def validate_findings(self, record):
        """Require already validated AI findings before applying any domain rule."""
        findings = record.get("ai")
        if not isinstance(findings, dict):
            raise AssessmentValidationError("Record must contain validated AI findings.")
        for key in self._AI_FLAGS:
            if not isinstance(findings.get(key), bool):
                raise AssessmentValidationError("AI finding must be true or false: " + key)

    def validate(self, record):
        """Validate both record inputs and the AI fields consumed by scoring."""
        self.validate_record(record)
        self.validate_findings(record)
