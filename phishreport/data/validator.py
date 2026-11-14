"""Validate new reports and supported historical schemas without mutation."""

from phishreport.model import (
    INPUT_FIELDS as INPUT_FIELDS,
)
from phishreport.model import (
    REPORT_FIELDS,
    _validate_legacy,
    _validate_result,
    _validate_rule_trace,
    _validate_summary,
    _validate_v1,
    _validate_v2,
    _validate_v3,
)


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

    _validate_v1 = staticmethod(_validate_v1)
