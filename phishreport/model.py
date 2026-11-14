"""Shared report contract foundations independent of storage and transports."""

import math
from collections.abc import Mapping
from dataclasses import InitVar, dataclass, field
from types import MappingProxyType

SCHEMA_VERSION = 3
SCHEMA_VERSION_KEY = "schema_version"

REPORT_FIELDS = {
    "channel",
    "sender",
    "message",
    "link",
    "file_name",
    "details",
    "score",
    "priority",
}

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


@dataclass(frozen=True, slots=True)
class RuleTrace:
    """Describe whether a rule matched and the score it produced, if any."""

    rule_name: str
    matched: bool
    score: int | None = None

    def as_dict(self) -> dict:
        """Return a JSON-compatible representation for interface adapters."""
        return {
            "rule_name": self.rule_name,
            "matched": self.matched,
            "score": self.score,
        }


@dataclass(frozen=True, slots=True)
class ExposureAnswers:
    """Preserve independent exposure observations, including historical labels."""

    clicked: bool | None = None
    downloaded: bool | None = None
    submitted_category: str | None = None
    disclosure_answered: bool | None = None

    def __post_init__(self) -> None:
        """Validate immutable scalar types without inferring or normalizing answers."""
        for value in (self.clicked, self.downloaded, self.disclosure_answered):
            if value is not None and type(value) is not bool:
                raise ValueError("Invalid exposure answer flag.")
        if self.submitted_category is not None and not isinstance(self.submitted_category, str):
            raise ValueError("Invalid exposure answer category.")


@dataclass(frozen=True, slots=True)
class AssessmentResult:
    """Own assessment values while preserving supported historical outcomes."""

    score: int | float | None
    priority: str | None
    reasons: tuple[str, ...] = ()
    checklist: tuple[str, ...] = ()
    matched_rule: str | None = None
    trace: tuple[RuleTrace, ...] = ()

    def __post_init__(self) -> None:
        """Validate scalar values and own guidance and validated rule traces."""
        if self.score is not None and (
            type(self.score) not in (int, float)
            or (type(self.score) is float and not math.isfinite(self.score))
        ):
            raise ValueError("Invalid assessment score.")
        if self.priority is not None and not isinstance(self.priority, str):
            raise ValueError("Invalid assessment priority.")
        if self.matched_rule is not None and not isinstance(self.matched_rule, str):
            raise ValueError("Invalid assessment matched rule.")
        for values in (self.reasons, self.checklist):
            if not isinstance(values, (list, tuple)) or any(
                not isinstance(value, str) for value in values
            ):
                raise ValueError("Invalid assessment guidance.")
        if not isinstance(self.trace, (list, tuple)) or any(
            not isinstance(step, RuleTrace) for step in self.trace
        ):
            raise ValueError("Invalid assessment trace.")
        if self.trace:
            _validate_rule_trace({
                "score": self.score,
                "matched_rule": self.matched_rule,
                "trace": [step.as_dict() for step in self.trace],
            })
        object.__setattr__(self, "reasons", tuple(self.reasons))
        object.__setattr__(self, "checklist", tuple(self.checklist))
        object.__setattr__(self, "trace", tuple(self.trace))


@dataclass(frozen=True, slots=True)
class Report:
    """Own original report data and expose a tolerant immutable history view."""

    source: InitVar[Mapping[str, object]]
    _payload: Mapping[str, object] = field(init=False, repr=False)
    schema_version: int | None = field(init=False)
    assessment_id: str | None = field(init=False)
    channel: str | None = field(init=False)
    message: str | None = field(init=False)
    sender: str | None = field(init=False)
    link: str | None = field(init=False)
    file_name: str | None = field(init=False)
    has_link: bool | None = field(init=False)
    has_file: bool | None = field(init=False)
    result: AssessmentResult | None = field(init=False)
    exposure: ExposureAnswers | None = field(init=False)
    has_nested_exposure: bool = field(init=False)
    emails: tuple[str, ...] = field(init=False)
    phone_numbers: tuple[str, ...] = field(init=False)
    ip_addresses: tuple[str, ...] = field(init=False)

    def __post_init__(self, source: Mapping[str, object]) -> None:
        """Snapshot all source data before projecting supported historical fields.

        Invalid JSON-shaped field values remain in the snapshot while the view
        exposes unknown values as None or empty tuples. Stored-schema validation
        is a separate boundary; this projection never repairs historical data.
        """
        if not isinstance(source, Mapping):
            raise ValueError("Report source must be an object.")
        payload = _freeze_json(source)
        object.__setattr__(self, "_payload", payload)
        version = payload.get(SCHEMA_VERSION_KEY)
        object.__setattr__(self, "schema_version", version if type(version) is int else None)
        for name in ("assessment_id", "channel", "message", "sender", "link", "file_name"):
            value = payload.get(name)
            object.__setattr__(self, name, value if isinstance(value, str) else None)
        for name in ("has_link", "has_file"):
            value = payload.get(name)
            object.__setattr__(self, name, value if type(value) is bool else None)

        result_source = payload.get("result")
        if not isinstance(result_source, Mapping) or not result_source:
            result_source = payload
        result = None
        if any(name in result_source for name in (
            "score", "priority", "reasons", "checklist", "matched_rule", "trace",
        )):
            score = result_source.get("score")
            if type(score) not in (int, float) or (
                type(score) is float and not math.isfinite(score)
            ):
                score = None
            priority = result_source.get("priority")
            if not isinstance(priority, str):
                priority = None
            matched_rule = result_source.get("matched_rule")
            if not isinstance(matched_rule, str):
                matched_rule = None
            guidance = {}
            for name in ("reasons", "checklist"):
                values = result_source.get(name)
                guidance[name] = (
                    tuple(value for value in values if isinstance(value, str))
                    if isinstance(values, (list, tuple)) else ()
                )
            trace = ()
            if all(name in result_source for name in ("matched_rule", "score", "trace")):
                candidate = {
                    "score": score,
                    "matched_rule": result_source["matched_rule"],
                    "trace": _thaw_json(result_source["trace"]),
                }
                try:
                    _validate_rule_trace(candidate)
                except ValueError:
                    pass
                else:
                    trace = tuple(RuleTrace(**step) for step in candidate["trace"])
            result = AssessmentResult(
                score, priority, guidance["reasons"], guidance["checklist"], matched_rule, trace,
            )
        object.__setattr__(self, "result", result)

        exposure_source = None
        nested = payload.get("exposure")
        has_nested_exposure = self.schema_version == SCHEMA_VERSION and isinstance(nested, Mapping)
        if has_nested_exposure:
            exposure_source = nested
        elif self.schema_version != SCHEMA_VERSION and any(name in payload for name in (
            "clicked", "downloaded", "submitted_category", "disclosure_answered",
        )):
            exposure_source = payload
        exposure = None
        if exposure_source is not None:
            answers = {}
            for name in ("clicked", "downloaded", "disclosure_answered"):
                value = exposure_source.get(name)
                answers[name] = value if type(value) is bool else None
            category = exposure_source.get("submitted_category")
            answers["submitted_category"] = category if isinstance(category, str) else None
            exposure = ExposureAnswers(**answers)
        object.__setattr__(self, "exposure", exposure)
        object.__setattr__(self, "has_nested_exposure", has_nested_exposure)

        details = payload.get("details")
        if not isinstance(details, Mapping):
            ai = payload.get("ai")
            details = ai.get("details") if isinstance(ai, Mapping) else None
        if not isinstance(details, Mapping):
            details = {}
        for name in ("emails", "phone_numbers", "ip_addresses"):
            values = details.get(name)
            projected = (
                tuple(value for value in values if isinstance(value, str))
                if isinstance(values, (list, tuple)) else ()
            )
            object.__setattr__(self, name, projected)


def _freeze_json(value: object) -> object:
    """Own an acyclic JSON-shaped value through recursively read-only containers.

    Copy mapping contents into read-only mappings and sequences into tuples.
    Preserve scalar values exactly; report-field validation belongs to the model
    contracts added separately. Never include rejected input in error messages.
    """
    error_message = "Report data must use JSON-compatible values and string object keys."
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(error_message)
        return MappingProxyType({key: _freeze_json(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item) for item in value)
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise ValueError(error_message)


def _thaw_json(value: object) -> object:
    """Serialize acyclic JSON-shaped data into independently owned containers.

    Return new dictionaries and lists without normalizing scalar values. Reject
    unsupported values without including private input in the error message.
    """
    error_message = "Report data must use JSON-compatible values and string object keys."
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise ValueError(error_message)
        return {key: _thaw_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_thaw_json(item) for item in value]
    if value is None or isinstance(value, (str, bool, int, float)):
        return value
    raise ValueError(error_message)


def _validate_new(record: dict) -> dict:
    """Return an unchanged valid v2 or v3 report, or raise ValueError."""
    if not isinstance(record, dict):
        raise ValueError("New reports must be objects.")
    version = record.get(SCHEMA_VERSION_KEY)
    if type(version) is not int or version not in (2, SCHEMA_VERSION):
        raise ValueError("Unsupported new report version.")
    if version == SCHEMA_VERSION:
        return _validate_v3(record)
    return _validate_v2(record)


def _validate_stored(record: dict) -> dict:
    """Validate supported history without inventing or normalizing data."""
    if not isinstance(record, dict):
        raise ValueError("Stored reports must be objects.")
    if SCHEMA_VERSION_KEY not in record:
        if set(record) == REPORT_FIELDS:
            return _validate_summary(record)
        return _validate_legacy(record)
    if (
        type(record[SCHEMA_VERSION_KEY]) is not int
        or record[SCHEMA_VERSION_KEY] not in (1, 2, SCHEMA_VERSION)
    ):
        raise ValueError("Unsupported report version.")
    if record[SCHEMA_VERSION_KEY] == SCHEMA_VERSION:
        return _validate_v3(record)
    if record[SCHEMA_VERSION_KEY] == 2:
        return _validate_v2(record)
    return _validate_v1(record)


def _validate_summary(record):
    """Return an unchanged legacy eight-field report after validating its fields.

    Raise ValueError for invalid types, detail lists, score or priority. This
    checks stored structure, not contact syntax or the original assessment.
    """
    if not isinstance(record, dict) or set(record) != REPORT_FIELDS:
        raise ValueError("Reports must contain exactly the eight agreed fields.")
    if not isinstance(record["channel"], str):
        raise ValueError("Invalid report channel.")
    if not isinstance(record["message"], str) or not record["message"].strip():
        raise ValueError("Invalid report message.")
    for key in ("sender", "link", "file_name"):
        if record[key] is not None and not isinstance(record[key], str):
            raise ValueError("Invalid report metadata.")

    # Store extraction as three lists, without normalizing or inventing values.
    details = record["details"]
    if not isinstance(details, dict) or set(details) != {
        "emails",
        "phone_numbers",
        "ip_addresses",
    }:
        raise ValueError("Invalid stored extraction.")
    for values in details.values():
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError("Invalid stored text lists.")
    if type(record["score"]) is not int or not 0 <= record["score"] <= 100:
        raise ValueError("Invalid stored score.")
    if record["priority"] not in ("LOW", "MEDIUM", "HIGH"):
        raise ValueError("Invalid stored priority.")
    return record


def _validate_legacy(record):
    """Return historical data after checking the fields that are present.

    Missing fields and unknown fields are retained unchanged. Validate both
    root and nested outcomes because either can reach the history display.
    Raise ValueError for unsafe stored field types; do not reassess the report.
    """
    for key in ("channel", "sender", "message", "link", "file_name", "submitted_category"):
        value = record.get(key)
        if value is not None and not isinstance(value, str):
            raise ValueError("Invalid legacy text field: " + key)
    for key in ("has_link", "has_file", "clicked", "downloaded"):
        value = record.get(key)
        if value is not None and type(value) is not bool:
            raise ValueError("Invalid legacy action field: " + key)

    result = record.get("result")
    if result is not None and not isinstance(result, dict):
        raise ValueError("Invalid legacy assessment.")

    # Both historical outcome locations reach the public display functions.
    for outcome in (record, result if result is not None else {}):
        priority = outcome.get("priority")
        if priority is not None and not isinstance(priority, str):
            raise ValueError("Invalid legacy priority.")
        value = outcome.get("score")
        if value is not None and type(value) not in (int, float):
            raise ValueError("Invalid legacy score.")
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("Invalid nonfinite legacy score.")
        for key in ("reasons", "checklist"):
            if key in outcome and (
                not isinstance(outcome[key], list)
                or any(not isinstance(item, str) for item in outcome[key])
            ):
                raise ValueError("Invalid legacy assessment list: " + key)

    if "details" in record:
        details = record["details"]
        if not isinstance(details, dict):
            raise ValueError("Invalid legacy details.")
        for key in ("emails", "phone_numbers", "ip_addresses"):
            if key in details and (
                not isinstance(details[key], list)
                or any(not isinstance(item, str) for item in details[key])
            ):
                raise ValueError("Invalid legacy extraction list: " + key)
    return record


def _validate_v1(record):
    """Validate the complete historical version-1 assessment."""
    if set(record) != INPUT_FIELDS | {SCHEMA_VERSION_KEY, "ai", "result"}:
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
    _validate_result(record["result"])
    for values in details.values():
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError("Invalid stored text lists.")
    return record


def _validate_v2(record):
    """Validate the exact version-2 storage contract without changing values."""
    if not isinstance(record, dict) or set(record) != {
        SCHEMA_VERSION_KEY,
        "channel",
        "message",
        "result",
    }:
        raise ValueError("Version-2 reports must contain exactly the four agreed fields.")
    if type(record[SCHEMA_VERSION_KEY]) is not int or record[SCHEMA_VERSION_KEY] != 2:
        raise ValueError("New reports must use schema version 2.")
    for key in ("channel", "message"):
        if not isinstance(record[key], str) or not record[key].strip():
            raise ValueError("Invalid report text: " + key)
    # Keep the original message intact; validation never strips or truncates it.
    # The merged RuleOutcome workflow writes traces to v2 reports too.
    _validate_result(record["result"], allow_rule_trace=True)
    return record


def _validate_v3(record: dict) -> dict:
    """Validate feedback-linked or exposure reports without changing values.

    The ten-field exposure form remains readable for existing reports. New
    exposure reports also carry an assessment ID so users can leave feedback.
    """
    if (
        not isinstance(record, dict)
        or type(record.get(SCHEMA_VERSION_KEY)) is not int
        or record[SCHEMA_VERSION_KEY] != SCHEMA_VERSION
    ):
        raise ValueError("Version-3 reports must use schema version 3.")
    exposure_fields = {
        SCHEMA_VERSION_KEY, "channel", "message", "result", "sender",
        "has_link", "link", "has_file", "file_name", "exposure",
    }
    feedback_fields = {
        SCHEMA_VERSION_KEY, "assessment_id", "channel", "message", "result",
    }
    fields = set(record)
    is_exposure = fields in (exposure_fields, exposure_fields | {"assessment_id"})
    if not is_exposure and fields != feedback_fields:
        raise ValueError("Version-3 reports must match a supported report shape.")
    if "assessment_id" in record:
        assessment_id = record["assessment_id"]
        if (
            not isinstance(assessment_id, str)
            or not assessment_id.strip()
            or len(assessment_id) > 100
        ):
            raise ValueError("Invalid assessment identifier.")
    for key in ("channel", "message"):
        if not isinstance(record[key], str) or not record[key].strip():
            raise ValueError("Invalid report text: " + key)
    if not is_exposure:
        _validate_result(record["result"], allow_rule_trace=True)
        return record

    if record["sender"] is not None and not isinstance(record["sender"], str):
        raise ValueError("Invalid report sender.")
    for key in ("link", "file_name"):
        value = record[key]
        if value is not None and (not isinstance(value, str) or not value.strip()):
            raise ValueError("Invalid report metadata: " + key)
    for key in ("has_link", "has_file"):
        if type(record[key]) is not bool:
            raise ValueError("Invalid report metadata flag: " + key)
    if record["has_link"] != (record["link"] is not None):
        raise ValueError("Report link and flag must agree.")
    if record["file_name"] is not None and not record["has_file"]:
        raise ValueError("A report filename requires a file clue.")

    exposure = record["exposure"]
    if not isinstance(exposure, dict) or set(exposure) != {
        "clicked", "downloaded", "submitted_category", "disclosure_answered",
    }:
        raise ValueError("Invalid report exposure fields.")
    for key in ("clicked", "downloaded"):
        if exposure[key] is not None and type(exposure[key]) is not bool:
            raise ValueError("Invalid exposure action: " + key)
    if type(exposure["disclosure_answered"]) is not bool:
        raise ValueError("Invalid disclosure answer flag.")
    if exposure["submitted_category"] not in (None, "password", "otp"):
        raise ValueError("Invalid submitted category.")
    if not exposure["disclosure_answered"] and exposure["submitted_category"] is not None:
        raise ValueError("Unanswered disclosure must have no submitted category.")
    _validate_result(record["result"], allow_rule_trace=True)
    return record


def _validate_result(result, *, allow_rule_trace=False):
    """Validate the score, priority, guidance and permitted explanation fields.

    Return None on success; raise ValueError without changing the result on
    failure. Four-field historical results remain valid. Newer v2 and v3
    reports may also carry the matched-rule trace. Empty guidance lists are
    accepted, but blank list entries are not.
    """
    required_fields = {
        "score",
        "priority",
        "reasons",
        "checklist",
    }
    optional_fields = {"matched_rule", "trace"} if allow_rule_trace else set()
    fields = set(result) if isinstance(result, dict) else set()
    if (
        not isinstance(result, dict)
        or not required_fields.issubset(fields)
        or not fields.issubset(required_fields | optional_fields)
        or (bool(fields.intersection(optional_fields)) and not optional_fields.issubset(fields))
    ):
        raise ValueError("Invalid stored assessment.")
    if type(result["score"]) is not int or not 0 <= result["score"] <= 100:
        raise ValueError("Invalid stored score.")
    if result["priority"] not in ("LOW", "MEDIUM", "HIGH"):
        raise ValueError("Invalid stored priority.")
    for key in ("reasons", "checklist"):
        values = result[key]
        if not isinstance(values, list) or any(
            not isinstance(value, str) or not value.strip() for value in values
        ):
            raise ValueError("Invalid stored text lists.")
    if optional_fields and optional_fields.issubset(fields):
        _validate_rule_trace(result)


def _validate_rule_trace(result):
    """Check that an optional trace ends at the recorded winning rule."""
    matched_rule = result["matched_rule"]
    trace = result["trace"]
    if not isinstance(matched_rule, str) or not matched_rule.strip():
        raise ValueError("Invalid matched rule.")
    if not isinstance(trace, list) or not trace:
        raise ValueError("Invalid stored rule trace.")
    trace_fields = {"rule_name", "matched", "score"}
    for step in trace:
        if not isinstance(step, dict) or set(step) != trace_fields:
            raise ValueError("Invalid stored rule trace step.")
        if not isinstance(step["rule_name"], str) or not step["rule_name"].strip():
            raise ValueError("Invalid stored rule name.")
        if type(step["matched"]) is not bool:
            raise ValueError("Invalid stored rule match flag.")
        score = step["score"]
        if step["matched"]:
            if type(score) is not int or not 0 <= score <= 100:
                raise ValueError("Invalid stored rule score.")
        elif score is not None:
            raise ValueError("Non-matching rules cannot have a score.")

    winning_step = trace[-1]
    if (
        any(step["matched"] for step in trace[:-1])
        or not winning_step["matched"]
        or winning_step["rule_name"] != matched_rule
        or winning_step["score"] != result["score"]
    ):
        raise ValueError("Stored rule trace does not match its assessment.")
