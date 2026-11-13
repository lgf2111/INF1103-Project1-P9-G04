"""Validate new reports and supported historical schemas without mutation."""

import math

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
        if type(record["schema_version"]) is not int or record["schema_version"] not in (1, 2, 3):
            raise ValueError("Unsupported report version.")
        if record["schema_version"] == 3:
            return self._validate_v3(record)
        if record["schema_version"] == 2:
            return self._validate_v2(record)
        return self._validate_v1(record)

    def _validate_summary(self, record):
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

    def _validate_result(self, result):
        """Validate assessment fields and an optional matched-rule trace.

        Return None on success; raise ValueError without changing the result on
        failure. Four-field historical results remain valid. Empty guidance lists
        are accepted, but blank list entries are not.
        """
        required_fields = {
            "score",
            "priority",
            "reasons",
            "checklist",
        }
        trace_fields = {"matched_rule", "trace"}
        if (
            not isinstance(result, dict)
            or not required_fields.issubset(result)
            or not set(result).issubset(required_fields | trace_fields)
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
        if trace_fields.intersection(result):
            if not trace_fields.issubset(result):
                raise ValueError("Invalid stored rule trace.")
            self._validate_rule_trace(result)

    @staticmethod
    def _validate_rule_trace(result):
        """Check that the trace ends at the matching rule and score."""
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

    def _validate_v2(self, record):
        """Validate the exact version-2 storage contract without changing values."""
        if not isinstance(record, dict) or set(record) != {
            "schema_version",
            "channel",
            "message",
            "result",
        }:
            raise ValueError("Version-2 reports must contain exactly the four agreed fields.")
        if type(record["schema_version"]) is not int or record["schema_version"] != 2:
            raise ValueError("New reports must use schema version 2.")
        for key in ("channel", "message"):
            if not isinstance(record[key], str) or not record[key].strip():
                raise ValueError("Invalid report text: " + key)
        # Keep the original message intact; validation never strips or truncates it.
        self._validate_result(record["result"])
        return record

    def _validate_v3(self, record: dict) -> dict:
        """Return an unchanged v3 report with explicit nullable exposure answers.

        Raise ValueError for malformed fields or inconsistent metadata/answers.
        Validation preserves unknown answers and never reassesses stored results.
        """
        if not isinstance(record, dict) or set(record) != {
            "schema_version", "channel", "message", "result", "sender",
            "has_link", "link", "has_file", "file_name", "exposure",
        }:
            raise ValueError("Version-3 reports must contain exactly the ten agreed fields.")
        if type(record["schema_version"]) is not int or record["schema_version"] != 3:
            raise ValueError("Exposure reports must use schema version 3.")
        for key in ("channel", "message"):
            if not isinstance(record[key], str) or not record[key].strip():
                raise ValueError("Invalid report text: " + key)
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
        self._validate_result(record["result"])
        return record

    def _validate_legacy(self, record):
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
