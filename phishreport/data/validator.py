"""Validate new reports and supported historical schemas without mutation."""

from phishreport.model import (
    REPORT_FIELDS,
    _validate_legacy,
    _validate_result,
    _validate_rule_trace,
    _validate_summary,
    _validate_v2,
    _validate_v3,
)

INPUT_FIELDS = {
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


class ReportValidator:
    """Own report schema rules independently of persistence and logging."""

    def validate_new(self, record: dict) -> dict:
        """Return an unchanged valid v2 or v3 report, or raise ValueError."""
        if not isinstance(record, dict):
            raise ValueError("New reports must be objects.")
        version = record.get("schema_version")
        if type(version) is not int or version not in (2, 3):
            raise ValueError("Unsupported new report version.")
        if version == 3:
            return self._validate_v3(record)
        return self._validate_v2(record)

    def validate_stored(self, record: dict) -> dict:
        """Validate supported history without inventing or normalizing data."""
        if not isinstance(record, dict):
            raise ValueError("Stored reports must be objects.")
        if "schema_version" not in record:
            if set(record) == REPORT_FIELDS:
                return self._validate_summary(record)
            return self._validate_legacy(record)
        if (
            type(record["schema_version"]) is not int
            or record["schema_version"] not in (1, 2, 3)
        ):
            raise ValueError("Unsupported report version.")
        if record["schema_version"] == 3:
            return self._validate_v3(record)
        if record["schema_version"] == 2:
            return self._validate_v2(record)
        return self._validate_v1(record)

    _validate_summary = staticmethod(_validate_summary)

    _validate_result = staticmethod(_validate_result)

    _validate_rule_trace = staticmethod(_validate_rule_trace)

    _validate_v2 = staticmethod(_validate_v2)

    _validate_v3 = staticmethod(_validate_v3)

    _validate_legacy = staticmethod(_validate_legacy)

    def _validate_v1(self, record):
        """Validate the complete historical version-1 assessment."""
        if set(record) != INPUT_FIELDS | {"schema_version", "ai", "result"}:
            raise ValueError("Incomplete versioned report.")
        if not isinstance(record["channel"], str):
            raise ValueError("Invalid report channel.")
        if not isinstance(record["message"], str) or not record["message"].strip():
            raise ValueError("Invalid report message.")
        for key in ("sender", "link", "file_name"):
            if record[key] is not None and not isinstance(record[key], str):
                raise ValueError("Invalid report metadata.")
        for key in ("has_link", "has_file", "clicked", "downloaded"):
            if type(record[key]) is not bool:
                raise ValueError("Invalid reported action.")
        if record["submitted_category"] not in (None, "password", "otp"):
            raise ValueError("Invalid submitted category.")
        ai = record["ai"]
        findings = {"credential_request", "suspicious", "insufficient_context"}
        if not isinstance(ai, dict) or set(ai) != findings | {"details"}:
            raise ValueError("Invalid stored AI findings.")
        if any(type(ai[key]) is not bool for key in findings):
            raise ValueError("Invalid stored AI finding types.")
        details = ai["details"]
        if not isinstance(details, dict) or set(details) != {
            "emails",
            "phone_numbers",
            "ip_addresses",
        }:
            raise ValueError("Invalid stored extraction.")
        self._validate_result(record["result"])
        for values in details.values():
            if not isinstance(values, list) or any(
                not isinstance(value, str) or not value.strip() for value in values
            ):
                raise ValueError("Invalid stored text lists.")
        return record
