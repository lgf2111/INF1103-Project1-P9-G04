"""Validate new reports and supported historical schemas without mutation."""

from phishreport.model import (
    INPUT_FIELDS as INPUT_FIELDS,
)
from phishreport.model import (
    REPORT_FIELDS as REPORT_FIELDS,
)
from phishreport.model import (
    _validate_legacy,
    _validate_new,
    _validate_result,
    _validate_rule_trace,
    _validate_stored,
    _validate_summary,
    _validate_v1,
    _validate_v2,
    _validate_v3,
)


class ReportValidator:
    """Expose model-owned report validation through the existing validator API."""

    validate_new = staticmethod(_validate_new)

    validate_stored = staticmethod(_validate_stored)

    _validate_summary = staticmethod(_validate_summary)

    _validate_result = staticmethod(_validate_result)

    _validate_rule_trace = staticmethod(_validate_rule_trace)

    _validate_v2 = staticmethod(_validate_v2)

    _validate_v3 = staticmethod(_validate_v3)

    _validate_legacy = staticmethod(_validate_legacy)

    _validate_v1 = staticmethod(_validate_v1)
