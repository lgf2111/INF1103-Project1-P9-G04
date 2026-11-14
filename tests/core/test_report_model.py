"""Immutable JSON ownership for the report model foundation."""

import math
from collections import UserDict
from copy import deepcopy
from types import MappingProxyType
from unittest.mock import Mock

import pytest

from phishreport import model
from phishreport.data import validator as data_validator
from phishreport.data.validator import ReportValidator
from phishreport.model import (
    INPUT_FIELDS,
    REPORT_FIELDS,
    SCHEMA_VERSION,
    SCHEMA_VERSION_KEY,
    _freeze_json,
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


def test_report_model_owns_schema_version_constants():
    assert SCHEMA_VERSION == 3
    assert SCHEMA_VERSION_KEY == "schema_version"


def test_freeze_json_owns_nested_input_and_unknown_legacy_fields():
    original = {
        "result": {"reasons": ["Original reason"], "trace": [{"matched": True}]},
        "unknown_legacy_extra": {"labels": ["original", {"details": [1, 2]}]},
    }

    frozen = _freeze_json(original)
    original["result"]["reasons"].append("Later reason")
    original["result"]["trace"][0]["matched"] = False
    original["unknown_legacy_extra"]["labels"][0] = "changed"
    original["unknown_legacy_extra"]["labels"][1]["details"].append(3)
    original["new_field"] = "not owned"

    assert isinstance(frozen, MappingProxyType)
    assert frozen["result"]["reasons"] == ("Original reason",)
    assert frozen["result"]["trace"][0]["matched"] is True
    assert frozen["unknown_legacy_extra"]["labels"][0] == "original"
    assert frozen["unknown_legacy_extra"]["labels"][1]["details"] == (1, 2)
    assert "new_field" not in frozen


def test_freeze_json_rejects_mutations_at_every_container_level():
    frozen = _freeze_json({"items": [{"values": [1]}]})

    with pytest.raises(TypeError):
        frozen["items"] = ()
    with pytest.raises(TypeError):
        frozen["items"][0] = {}
    with pytest.raises(TypeError):
        frozen["items"][0]["values"] = ()
    with pytest.raises(AttributeError):
        frozen["items"][0]["values"].append(2)


def test_freeze_json_does_not_retain_mutable_aliases_between_original_branches():
    shared_list = ["kept"]
    shared_mapping = {"items": shared_list}
    original = {"left": shared_mapping, "right": shared_mapping, "items": shared_list}

    frozen = _freeze_json(original)
    shared_mapping["extra"] = "new"
    shared_list.clear()

    assert frozen["left"]["items"] == frozen["right"]["items"] == frozen["items"] == ("kept",)
    assert frozen["left"] is not shared_mapping and frozen["right"] is not shared_mapping
    assert frozen["left"]["items"] is not shared_list
    assert "extra" not in frozen["left"] and "extra" not in frozen["right"]


def test_freeze_json_accepts_mapping_protocol_and_tuples_without_mutable_aliases():
    original = UserDict({"items": (["before"],)})

    frozen = _freeze_json(original)
    original["items"][0].append("after")

    assert isinstance(frozen, MappingProxyType)
    assert frozen["items"] == (("before",),)


@pytest.mark.parametrize("value", [None, "", "Text", True, False, 0, -3, 2**80, 0.0, -1.25])
def test_freeze_json_preserves_scalar_values_without_coercion(value):
    assert _freeze_json(value) is value


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_freeze_json_does_not_normalize_nonfinite_legacy_float_values(value):
    frozen = _freeze_json(value)

    assert frozen is value
    assert math.isnan(frozen) if math.isnan(value) else frozen == value


@pytest.mark.parametrize("value", [object(), {"private-value"}, bytearray(b"private"), b"private"])
def test_freeze_json_rejects_unsupported_types_with_fixed_safe_message(value):
    original = {"items": ["preserved", value]}

    with pytest.raises(ValueError) as caught:
        _freeze_json(original)

    assert "private" not in str(caught.value)
    assert str(caught.value) == (
        "Report data must use JSON-compatible values and string object keys."
    )
    assert original["items"][0] == "preserved" and original["items"][1] is value


@pytest.mark.parametrize("key", [1, True, None, ("private",)])
def test_freeze_json_rejects_non_string_mapping_keys_without_changing_input(key):
    nested = ["preserved"]
    original = {"valid": nested, key: "private-value"}

    with pytest.raises(ValueError) as caught:
        _freeze_json(original)

    assert str(caught.value) == (
        "Report data must use JSON-compatible values and string object keys."
    )
    assert original["valid"] is nested and nested == ["preserved"]
    assert original[key] == "private-value"


def test_freeze_json_error_does_not_format_unsupported_objects():
    class Unprintable:
        def __repr__(self):
            raise AssertionError("Unsupported data must not be formatted")

    with pytest.raises(ValueError, match="JSON-compatible"):
        _freeze_json({"unknown": Unprintable()})


def test_rule_trace_validator_has_one_canonical_body_and_static_public_access():
    assert ReportValidator._validate_rule_trace is _validate_rule_trace
    assert ReportValidator()._validate_rule_trace is _validate_rule_trace


@pytest.mark.parametrize("score", [0, 60, 100])
@pytest.mark.parametrize("early_nonmatches", [0, 2])
def test_rule_trace_accepts_single_final_winner_without_mutating_input(score, early_nonmatches):
    result = {
        "matched_rule": "Winner", "score": score,
        "trace": [
            {"rule_name": f"Earlier {index}", "matched": False, "score": None}
            for index in range(early_nonmatches)
        ] + [{"rule_name": "Winner", "matched": True, "score": score}],
    }
    before = deepcopy(result)

    assert _validate_rule_trace(result) is None
    assert ReportValidator._validate_rule_trace(result) is None
    assert ReportValidator()._validate_rule_trace(result) is None
    assert result == before


@pytest.mark.parametrize("updates,expected", [
    ({"matched_rule": " "}, "Invalid matched rule."),
    ({"matched_rule": None}, "Invalid matched rule."),
    ({"matched_rule": 1}, "Invalid matched rule."),
    ({"trace": []}, "Invalid stored rule trace."),
    ({"trace": ()}, "Invalid stored rule trace."),
    ({"trace": None}, "Invalid stored rule trace."),
    ({"trace": [None]}, "Invalid stored rule trace step."),
    ({"trace": [{"rule_name": "Winner", "matched": True}]}, "Invalid stored rule trace step."),
    ({"trace": [{"rule_name": "Winner", "matched": True, "score": 60, "extra": 1}]},
     "Invalid stored rule trace step."),
    ({"trace": [{"rule_name": " ", "matched": True, "score": 60}]}, "Invalid stored rule name."),
    ({"trace": [{"rule_name": None, "matched": True, "score": 60}]}, "Invalid stored rule name."),
    ({"trace": [{"rule_name": "Winner", "matched": 1, "score": 60}]},
     "Invalid stored rule match flag."),
    ({"trace": [{"rule_name": "Winner", "matched": "yes", "score": 60}]},
     "Invalid stored rule match flag."),
    ({"trace": [{"rule_name": "Winner", "matched": False, "score": 0}]},
     "Non-matching rules cannot have a score."),
    ({"trace": [{"rule_name": "Winner", "matched": True, "score": None}]},
     "Invalid stored rule score."),
    ({"trace": [{"rule_name": "Winner", "matched": True, "score": True}]},
     "Invalid stored rule score."),
    ({"trace": [{"rule_name": "Winner", "matched": True, "score": -1}]},
     "Invalid stored rule score."),
    ({"trace": [{"rule_name": "Winner", "matched": True, "score": 101}]},
     "Invalid stored rule score."),
    ({"trace": [{"rule_name": "Winner", "matched": True, "score": 60.0}]},
     "Invalid stored rule score."),
    ({"trace": [{"rule_name": "Winner", "matched": True, "score": float("nan")}]},
     "Invalid stored rule score."),
    ({"trace": [{"rule_name": "Winner", "matched": False, "score": None}]},
     "Stored rule trace does not match its assessment."),
    ({"trace": [{"rule_name": "Earlier", "matched": True, "score": 10},
                {"rule_name": "Winner", "matched": True, "score": 60}]},
     "Stored rule trace does not match its assessment."),
    ({"trace": [{"rule_name": "Different", "matched": True, "score": 60}]},
     "Stored rule trace does not match its assessment."),
    ({"trace": [{"rule_name": "Winner", "matched": True, "score": 59}]},
     "Stored rule trace does not match its assessment."),
])
def test_rule_trace_rejects_invalid_winning_trace_without_mutation(updates, expected):
    result = {
        "matched_rule": "Winner", "score": 60,
        "trace": [{"rule_name": "Winner", "matched": True, "score": 60}],
    }
    result.update(updates)
    before = deepcopy(result)

    with pytest.raises(ValueError) as caught:
        _validate_rule_trace(result)

    assert str(caught.value) == expected
    assert result == before


@pytest.mark.parametrize("missing", ["matched_rule", "trace", "score"])
def test_rule_trace_keeps_prevalidated_result_precondition(missing):
    result = {
        "matched_rule": "Winner", "score": 60,
        "trace": [{"rule_name": "Winner", "matched": True, "score": 60}],
    }
    del result[missing]

    with pytest.raises(KeyError) as caught:
        _validate_rule_trace(result)

    assert caught.value.args == (missing,)


@pytest.fixture
def assessment_result():
    return {"score": 60, "priority": "MEDIUM", "reasons": [], "checklist": []}


def test_result_validator_has_one_canonical_body_and_compatible_instance_access(assessment_result):
    assert ReportValidator._validate_result is _validate_result
    assert ReportValidator()._validate_result is _validate_result
    assert ReportValidator()._validate_result(assessment_result) is None


@pytest.mark.parametrize("score,priority", [(0, "HIGH"), (60, "MEDIUM"), (100, "LOW")])
@pytest.mark.parametrize("allow_rule_trace", [False, True])
def test_result_validation_accepts_historical_fields_without_applying_scoring_rules(
    assessment_result, score, priority, allow_rule_trace,
):
    assessment_result.update(score=score, priority=priority)
    assessment_result["reasons"] = ["  Preserved reason  "]
    before = deepcopy(assessment_result)

    assert _validate_result(assessment_result, allow_rule_trace=allow_rule_trace) is None
    assert assessment_result == before


def test_result_validation_accepts_empty_guidance_lists(assessment_result):
    assert _validate_result(assessment_result) is None
    assert assessment_result["reasons"] == assessment_result["checklist"] == []


def test_result_validation_calls_canonical_trace_only_for_complete_opted_in_trace(
    assessment_result, monkeypatch,
):
    trace = Mock(wraps=model._validate_rule_trace)
    monkeypatch.setattr(model, "_validate_rule_trace", trace)
    assert _validate_result(assessment_result, allow_rule_trace=True) is None
    trace.assert_not_called()
    assessment_result.update(
        matched_rule="Winner", trace=[{"rule_name": "Winner", "matched": True, "score": 60}],
    )
    before = deepcopy(assessment_result)

    assert _validate_result(assessment_result, allow_rule_trace=True) is None

    trace.assert_called_once_with(assessment_result)
    assert assessment_result == before


@pytest.mark.parametrize("missing", ["score", "priority", "reasons", "checklist"])
def test_result_validation_rejects_missing_required_fields(assessment_result, missing):
    del assessment_result[missing]
    before = deepcopy(assessment_result)

    with pytest.raises(ValueError, match="Invalid stored assessment"):
        _validate_result(assessment_result)

    assert assessment_result == before


@pytest.mark.parametrize("value", [None, [], "assessment", 60])
def test_result_validation_rejects_non_dictionary_results(value):
    with pytest.raises(ValueError, match="Invalid stored assessment"):
        _validate_result(value)


@pytest.mark.parametrize("updates,allow_rule_trace", [
    ({"extra": "Not allowed"}, False),
    ({"extra": "Not allowed"}, True),
    ({"matched_rule": "Winner"}, True),
    ({"trace": []}, True),
    ({"matched_rule": "Winner", "trace": []}, False),
])
def test_result_validation_requires_exact_fields_and_explicit_complete_trace_pair(
    assessment_result, updates, allow_rule_trace,
):
    assessment_result.update(updates)
    before = deepcopy(assessment_result)

    with pytest.raises(ValueError, match="Invalid stored assessment"):
        _validate_result(assessment_result, allow_rule_trace=allow_rule_trace)

    assert assessment_result == before


@pytest.mark.parametrize("score", [True, False, None, -1, 101, 60.0, float("nan"), "60"])
def test_result_validation_rejects_non_integer_or_out_of_range_scores(assessment_result, score):
    assessment_result["score"] = score
    before = deepcopy(assessment_result)

    with pytest.raises(ValueError, match="Invalid stored score"):
        _validate_result(assessment_result)

    assert assessment_result == before


@pytest.mark.parametrize("priority", [None, "", "low", "CRITICAL", [], {}])
def test_result_validation_rejects_unknown_priorities(assessment_result, priority):
    assessment_result["priority"] = priority
    before = deepcopy(assessment_result)

    with pytest.raises(ValueError, match="Invalid stored priority"):
        _validate_result(assessment_result)

    assert assessment_result == before


@pytest.mark.parametrize("field", ["reasons", "checklist"])
@pytest.mark.parametrize("values", [None, (), "Reason", [""], [" \t"], [1], [True], [{}]])
def test_result_validation_rejects_invalid_guidance_without_coercion(
    assessment_result, field, values,
):
    assessment_result[field] = values
    before = deepcopy(assessment_result)

    with pytest.raises(ValueError, match="Invalid stored text lists"):
        _validate_result(assessment_result)

    assert assessment_result == before


def test_result_validation_propagates_trace_mismatch_and_preserves_failure_order(assessment_result):
    assessment_result.update(
        matched_rule="Winner", trace=[{"rule_name": "Winner", "matched": True, "score": 59}],
    )
    before = deepcopy(assessment_result)
    with pytest.raises(ValueError, match="Stored rule trace does not match"):
        _validate_result(assessment_result, allow_rule_trace=True)
    assert assessment_result == before
    assessment_result.update(score=True, priority="INVALID")

    with pytest.raises(ValueError, match="Invalid stored score"):
        _validate_result(assessment_result, allow_rule_trace=True)


@pytest.fixture
def version_two_report(assessment_result):
    return {
        "schema_version": 2, "channel": " chat ", "message": " Original Message\n  ",
        "result": assessment_result,
    }


@pytest.mark.parametrize("with_trace", [False, True])
def test_v2_validator_returns_original_record_without_normalizing(version_two_report, with_trace):
    if with_trace:
        version_two_report["result"].update(
            matched_rule="Winner", trace=[{"rule_name": "Winner", "matched": True, "score": 60}],
        )
    before = deepcopy(version_two_report)

    assert _validate_v2(version_two_report) is version_two_report
    assert ReportValidator._validate_v2 is _validate_v2
    assert ReportValidator()._validate_v2 is _validate_v2
    assert ReportValidator()._validate_v2(version_two_report) is version_two_report
    assert ReportValidator().validate_new(version_two_report) is version_two_report
    assert ReportValidator().validate_stored(version_two_report) is version_two_report
    assert version_two_report == before


@pytest.mark.parametrize("root", [None, [], "report", 2])
def test_v2_validator_rejects_non_dictionary_reports(root):
    with pytest.raises(ValueError) as caught:
        _validate_v2(root)

    assert str(caught.value) == "Version-2 reports must contain exactly the four agreed fields."


@pytest.mark.parametrize("missing", ["schema_version", "channel", "message", "result"])
def test_v2_validator_requires_all_four_fields(version_two_report, missing):
    del version_two_report[missing]
    before = deepcopy(version_two_report)

    with pytest.raises(ValueError, match="exactly the four agreed fields"):
        _validate_v2(version_two_report)

    assert version_two_report == before


def test_v2_validator_rejects_extra_fields_before_version_validation(version_two_report):
    version_two_report.update(extra="not allowed", schema_version=True)
    before = deepcopy(version_two_report)

    with pytest.raises(ValueError, match="exactly the four agreed fields"):
        _validate_v2(version_two_report)

    assert version_two_report == before


@pytest.mark.parametrize("version", [None, True, False, 2.0, "2", 1, 3])
def test_v2_validator_requires_exact_integer_version_two(version_two_report, version):
    version_two_report["schema_version"] = version
    before = deepcopy(version_two_report)

    with pytest.raises(ValueError) as caught:
        _validate_v2(version_two_report)

    assert str(caught.value) == "New reports must use schema version 2."
    assert version_two_report == before


@pytest.mark.parametrize("field", ["channel", "message"])
@pytest.mark.parametrize("value", [None, "", " \t\n", 1, True, []])
def test_v2_validator_rejects_invalid_text_without_coercion(version_two_report, field, value):
    version_two_report[field] = value
    before = deepcopy(version_two_report)

    with pytest.raises(ValueError) as caught:
        _validate_v2(version_two_report)

    assert str(caught.value) == "Invalid report text: " + field
    assert version_two_report == before


@pytest.mark.parametrize("updates,expected", [
    ({"score": True}, "Invalid stored score."),
    ({"reasons": [""]}, "Invalid stored text lists."),
    ({"matched_rule": "Winner"}, "Invalid stored assessment."),
    ({"matched_rule": "Winner", "trace": [
        {"rule_name": "Winner", "matched": True, "score": 59},
    ]}, "Stored rule trace does not match its assessment."),
])
def test_v2_validator_reuses_canonical_result_and_trace_validation(
    version_two_report, updates, expected,
):
    version_two_report["result"].update(updates)
    before = deepcopy(version_two_report)

    with pytest.raises(ValueError) as caught:
        _validate_v2(version_two_report)

    assert str(caught.value) == expected
    assert version_two_report == before


def test_v2_validator_calls_canonical_result_with_trace_opt_in(version_two_report, monkeypatch):
    validate_result = Mock(wraps=model._validate_result)
    monkeypatch.setattr(model, "_validate_result", validate_result)

    assert _validate_v2(version_two_report) is version_two_report

    validate_result.assert_called_once_with(version_two_report["result"], allow_rule_trace=True)


@pytest.fixture
def version_three_exposure(assessment_result):
    return {
        "schema_version": 3, "channel": " chat ", "message": " Original Message\n  ",
        "result": assessment_result, "sender": None,
        "has_link": True, "link": " https://example.test/login ",
        "has_file": True, "file_name": None,
        "exposure": {
            "clicked": None, "downloaded": False,
            "submitted_category": None, "disclosure_answered": False,
        },
    }


@pytest.mark.parametrize("shape", ["feedback", "historical_exposure", "identified_exposure"])
def test_v3_validator_preserves_three_supported_shapes_and_original_identifiers(
    version_three_exposure, shape,
):
    record = version_three_exposure
    if shape == "feedback":
        record = {key: record[key] for key in ("schema_version", "channel", "message", "result")}
    if shape != "historical_exposure":
        record["assessment_id"] = " " + "x" * 98 + " "
    record["result"].update(
        matched_rule="Winner", trace=[{"rule_name": "Winner", "matched": True, "score": 60}],
    )
    before = deepcopy(record)

    assert _validate_v3(record) is record
    assert ReportValidator._validate_v3 is _validate_v3
    assert ReportValidator()._validate_v3 is _validate_v3
    assert ReportValidator().validate_new(record) is record
    assert ReportValidator().validate_stored(record) is record
    assert record == before
    assert ("assessment_id" in record) is (shape != "historical_exposure")
    if "exposure" in record:
        assert record["exposure"]["clicked"] is None
        assert record["exposure"]["downloaded"] is False
        assert record["has_file"] is True and record["file_name"] is None


@pytest.mark.parametrize("answers", [
    (None, None, None, False), (False, False, None, True),
    (True, False, "password", True), (False, True, "otp", True),
])
def test_v3_validator_preserves_unknown_and_confirmed_exposure_answers(
    version_three_exposure, answers,
):
    version_three_exposure["exposure"] = dict(zip(
        ("clicked", "downloaded", "submitted_category", "disclosure_answered"), answers,
    ))
    before = deepcopy(version_three_exposure)

    assert _validate_v3(version_three_exposure) is version_three_exposure
    assert version_three_exposure == before


@pytest.mark.parametrize("root", [None, [], "report"])
def test_v3_validator_rejects_non_mapping_roots_at_version_boundary(root):
    with pytest.raises(ValueError, match="Version-3 reports must use schema version 3"):
        _validate_v3(root)


@pytest.mark.parametrize("version", [None, True, False, 3.0, "3", 2])
def test_v3_validator_requires_exact_current_integer_version(version_three_exposure, version):
    version_three_exposure["schema_version"] = version
    before = deepcopy(version_three_exposure)

    with pytest.raises(ValueError, match="Version-3 reports must use schema version 3"):
        _validate_v3(version_three_exposure)

    assert version_three_exposure == before


@pytest.mark.parametrize("missing", ["channel", "message", "result", "exposure"])
def test_v3_validator_rejects_incomplete_exposure_shapes(version_three_exposure, missing):
    del version_three_exposure[missing]
    before = deepcopy(version_three_exposure)

    with pytest.raises(ValueError, match="supported report shape"):
        _validate_v3(version_three_exposure)

    assert version_three_exposure == before


def test_v3_validator_rejects_extra_fields_before_identifier_validation(version_three_exposure):
    version_three_exposure.update(extra="not supported", assessment_id=None)
    before = deepcopy(version_three_exposure)

    with pytest.raises(ValueError, match="supported report shape"):
        _validate_v3(version_three_exposure)

    assert version_three_exposure == before


@pytest.mark.parametrize("identifier", [None, True, "", " \t ", "x" * 101])
def test_v3_validator_rejects_invalid_identifiers_without_inventing_replacements(
    version_three_exposure, identifier,
):
    version_three_exposure["assessment_id"] = identifier
    before = deepcopy(version_three_exposure)

    with pytest.raises(ValueError, match="Invalid assessment identifier"):
        _validate_v3(version_three_exposure)

    assert version_three_exposure == before


@pytest.mark.parametrize("updates,expected", [
    ({"channel": " "}, "Invalid report text: channel"),
    ({"message": None}, "Invalid report text: message"),
    ({"sender": 1}, "Invalid report sender."),
    ({"link": " "}, "Invalid report metadata: link"),
    ({"file_name": False}, "Invalid report metadata: file_name"),
    ({"has_link": 1}, "Invalid report metadata flag: has_link"),
    ({"has_file": None}, "Invalid report metadata flag: has_file"),
    ({"link": None}, "Report link and flag must agree."),
    ({"has_link": False}, "Report link and flag must agree."),
    ({"has_file": False, "file_name": "file.pdf"}, "A report filename requires a file clue."),
    ({"exposure": {}}, "Invalid report exposure fields."),
])
def test_v3_validator_rejects_invalid_source_metadata_without_mutation(
    version_three_exposure, updates, expected,
):
    version_three_exposure.update(updates)
    before = deepcopy(version_three_exposure)

    with pytest.raises(ValueError) as caught:
        _validate_v3(version_three_exposure)

    assert str(caught.value) == expected
    assert version_three_exposure == before


@pytest.mark.parametrize("updates,expected", [
    ({"clicked": 1}, "Invalid exposure action: clicked"),
    ({"downloaded": "no"}, "Invalid exposure action: downloaded"),
    ({"disclosure_answered": None}, "Invalid disclosure answer flag."),
    ({"submitted_category": "email"}, "Invalid submitted category."),
    ({"submitted_category": "password"}, "Unanswered disclosure must have no submitted category."),
    ({"extra": False}, "Invalid report exposure fields."),
])
def test_v3_validator_rejects_invalid_exposure_answer_cross_fields(
    version_three_exposure, updates, expected,
):
    version_three_exposure["exposure"].update(updates)
    before = deepcopy(version_three_exposure)

    with pytest.raises(ValueError) as caught:
        _validate_v3(version_three_exposure)

    assert str(caught.value) == expected
    assert version_three_exposure == before


@pytest.mark.parametrize("shape", ["feedback", "exposure"])
def test_v3_validator_uses_canonical_result_validation_for_each_result_branch(
    version_three_exposure, monkeypatch, shape,
):
    record = version_three_exposure
    if shape == "feedback":
        record = {key: record[key] for key in ("schema_version", "channel", "message", "result")}
        record["assessment_id"] = "stable-id"
    validate_result = Mock(wraps=model._validate_result)
    monkeypatch.setattr(model, "_validate_result", validate_result)

    assert _validate_v3(record) is record

    validate_result.assert_called_once_with(record["result"], allow_rule_trace=True)
    record["result"]["matched_rule"] = "Winner"
    with pytest.raises(ValueError, match="Invalid stored assessment"):
        _validate_v3(record)
    record["result"]["trace"] = [{"rule_name": "Winner", "matched": True, "score": 59}]
    with pytest.raises(ValueError, match="Stored rule trace does not match"):
        _validate_v3(record)


@pytest.mark.parametrize("record", [
    {},
    {"message": None, "result": None, "clicked": None, "has_link": None},
    {"channel": "", "sender": None, "message": "  ", "priority": "custom historical label",
     "score": -12.5, "reasons": ["", "  "], "checklist": [],
     "details": {"emails": [""], "unknown": {"values": [1, None]}},
     "unknown_extra": {"values": ["unchanged", None]}},
    {"score": 150, "result": {"score": -100, "priority": "", "reasons": [""],
                               "unknown_extra": {"values": [False]}}},
])
def test_legacy_validator_preserves_optional_and_unknown_historical_values(record):
    before = deepcopy(record)

    assert _validate_legacy(record) is record
    assert ReportValidator._validate_legacy is _validate_legacy
    assert ReportValidator()._validate_legacy is _validate_legacy
    assert ReportValidator().validate_stored(record) is record
    assert record == before
    assert ("result" in record) is ("result" in before)
    assert "assessment_id" not in record


@pytest.mark.parametrize("location", ["root", "nested"])
@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_legacy_validator_rejects_known_nonfinite_scores_at_either_location(location, value):
    outcome = {"score": value}
    record = outcome if location == "root" else {"result": outcome}
    before = deepcopy(record)

    with pytest.raises(ValueError) as caught:
        _validate_legacy(record)

    assert str(caught.value) == "Invalid nonfinite legacy score."
    assert record == before


def test_legacy_validator_does_not_reinterpret_nonfinite_unknown_extra_fields():
    value = float("nan")
    record = {"unknown_extra": {"unrecognized_value": value}, "score": 0}

    assert _validate_legacy(record) is record
    frozen = _freeze_json(record)
    assert frozen["unknown_extra"]["unrecognized_value"] is value


@pytest.mark.parametrize("location", ["root", "nested"])
@pytest.mark.parametrize("updates,expected", [
    ({"score": True}, "Invalid legacy score."),
    ({"score": "60"}, "Invalid legacy score."),
    ({"priority": 1}, "Invalid legacy priority."),
    ({"reasons": None}, "Invalid legacy assessment list: reasons"),
    ({"checklist": ()}, "Invalid legacy assessment list: checklist"),
    ({"reasons": ["valid", 1]}, "Invalid legacy assessment list: reasons"),
])
def test_legacy_validator_checks_root_and_nested_outcomes_without_mutation(
    location, updates, expected,
):
    record = deepcopy(updates) if location == "root" else {"result": deepcopy(updates)}
    before = deepcopy(record)

    with pytest.raises(ValueError) as caught:
        _validate_legacy(record)

    assert str(caught.value) == expected
    assert record == before


@pytest.mark.parametrize("record,expected", [
    ({"sender": 1}, "Invalid legacy text field: sender"),
    ({"submitted_category": False}, "Invalid legacy text field: submitted_category"),
    ({"clicked": 1}, "Invalid legacy action field: clicked"),
    ({"has_file": "yes"}, "Invalid legacy action field: has_file"),
    ({"result": []}, "Invalid legacy assessment."),
    ({"details": None}, "Invalid legacy details."),
    ({"details": {"emails": "not a list"}}, "Invalid legacy extraction list: emails"),
    ({"details": {"phone_numbers": [None]}}, "Invalid legacy extraction list: phone_numbers"),
    ({"details": {"ip_addresses": ("127.0.0.1",)}}, "Invalid legacy extraction list: ip_addresses"),
])
def test_legacy_validator_rejects_unsafe_known_field_types_without_mutation(record, expected):
    before = deepcopy(record)

    with pytest.raises(ValueError) as caught:
        _validate_legacy(record)

    assert str(caught.value) == expected
    assert record == before


def test_legacy_validator_keeps_validation_order_and_dict_precondition():
    record = {"message": 1, "score": True}
    with pytest.raises(ValueError, match="Invalid legacy text field: message"):
        _validate_legacy(record)

    with pytest.raises(AttributeError):
        _validate_legacy(None)


@pytest.fixture
def summary_report():
    return {
        "channel": "", "sender": "", "message": " Original Message\n ",
        "link": None, "file_name": " ",
        "details": {"emails": [" original text "], "phone_numbers": [], "ip_addresses": []},
        "score": 60, "priority": "MEDIUM",
    }


@pytest.mark.parametrize("score,priority", [(0, "HIGH"), (100, "LOW")])
def test_summary_validator_preserves_exact_historical_record_and_shared_field_set(
    summary_report, score, priority,
):
    summary_report.update(score=score, priority=priority)
    before = deepcopy(summary_report)

    assert REPORT_FIELDS is data_validator.REPORT_FIELDS
    assert type(REPORT_FIELDS) is set
    assert REPORT_FIELDS == {
        "channel", "sender", "message", "link", "file_name", "details", "score", "priority",
    }
    assert ReportValidator._validate_summary is _validate_summary
    assert ReportValidator()._validate_summary is _validate_summary
    assert _validate_summary(summary_report) is summary_report
    assert ReportValidator._validate_summary(summary_report) is summary_report
    assert ReportValidator().validate_stored(summary_report) is summary_report
    assert summary_report == before
    assert "schema_version" not in summary_report and "assessment_id" not in summary_report


@pytest.mark.parametrize("root", [None, [], "report"])
def test_summary_validator_rejects_invalid_roots(root):
    with pytest.raises(ValueError, match="exactly the eight agreed fields"):
        _validate_summary(root)


@pytest.mark.parametrize("missing", [
    "channel", "sender", "message", "link", "file_name", "details", "score", "priority",
])
def test_summary_validator_requires_each_agreed_field(summary_report, missing):
    del summary_report[missing]
    before = deepcopy(summary_report)

    with pytest.raises(ValueError, match="exactly the eight agreed fields"):
        _validate_summary(summary_report)

    assert summary_report == before


def test_summary_validator_rejects_extra_fields_before_checking_values(summary_report):
    summary_report.update(extra="Not allowed", message=None)
    before = deepcopy(summary_report)

    with pytest.raises(ValueError, match="exactly the eight agreed fields"):
        _validate_summary(summary_report)

    assert summary_report == before


@pytest.mark.parametrize("updates,expected", [
    ({"channel": None}, "Invalid report channel."),
    ({"message": " \t "}, "Invalid report message."),
    ({"message": False}, "Invalid report message."),
    ({"sender": 1}, "Invalid report metadata."),
    ({"link": False}, "Invalid report metadata."),
    ({"file_name": []}, "Invalid report metadata."),
    ({"details": None}, "Invalid stored extraction."),
    ({"details": {"emails": []}}, "Invalid stored extraction."),
    ({"details": {"emails": [], "phone_numbers": [], "ip_addresses": [], "extra": []}},
     "Invalid stored extraction."),
    ({"details": {"emails": (), "phone_numbers": [], "ip_addresses": []}},
     "Invalid stored text lists."),
    ({"details": {"emails": [" "], "phone_numbers": [], "ip_addresses": []}},
     "Invalid stored text lists."),
    ({"details": {"emails": [], "phone_numbers": ["12345678", None], "ip_addresses": []}},
     "Invalid stored text lists."),
    ({"score": True}, "Invalid stored score."),
    ({"score": 0.0}, "Invalid stored score."),
    ({"score": float("nan")}, "Invalid stored score."),
    ({"score": -1}, "Invalid stored score."),
    ({"score": 101}, "Invalid stored score."),
    ({"priority": "medium"}, "Invalid stored priority."),
    ({"priority": None}, "Invalid stored priority."),
])
def test_summary_validator_preserves_known_field_validation_and_error_messages(
    summary_report, updates, expected,
):
    summary_report.update(updates)
    before = deepcopy(summary_report)

    with pytest.raises(ValueError) as caught:
        _validate_summary(summary_report)

    assert str(caught.value) == expected
    assert summary_report == before


def test_summary_validator_accepts_empty_extraction_and_preserves_validation_order(summary_report):
    summary_report["details"] = {"emails": [], "phone_numbers": [], "ip_addresses": []}
    assert _validate_summary(summary_report) is summary_report
    summary_report.update(score=True, priority="INVALID")

    with pytest.raises(ValueError, match="Invalid stored score"):
        _validate_summary(summary_report)


@pytest.fixture
def version_one_report(assessment_result):
    return {
        "schema_version": 1, "channel": "", "sender": "", "message": " Original Message\n ",
        "has_link": False, "link": None, "has_file": False, "file_name": " ",
        "clicked": False, "downloaded": False, "submitted_category": None,
        "ai": {
            "credential_request": False, "suspicious": True, "insufficient_context": False,
            "details": {"emails": [], "phone_numbers": [], "ip_addresses": []},
        },
        "result": assessment_result,
    }


@pytest.mark.parametrize("emails", [[], [" original extraction "]])
def test_v1_validator_preserves_complete_historical_report_and_shared_input_fields(
    version_one_report, emails,
):
    version_one_report["ai"]["details"]["emails"] = emails
    before = deepcopy(version_one_report)

    assert INPUT_FIELDS is data_validator.INPUT_FIELDS
    assert type(INPUT_FIELDS) is set
    assert INPUT_FIELDS == {
        "channel", "sender", "message", "has_link", "link", "has_file", "file_name",
        "clicked", "downloaded", "submitted_category",
    }
    assert ReportValidator._validate_v1 is _validate_v1
    assert ReportValidator()._validate_v1 is _validate_v1
    assert _validate_v1(version_one_report) is version_one_report
    assert ReportValidator().validate_stored(version_one_report) is version_one_report
    assert version_one_report == before
    assert version_one_report["schema_version"] == 1
    assert "assessment_id" not in version_one_report


@pytest.mark.parametrize("missing", ["schema_version", "channel", "has_file", "ai", "result"])
def test_v1_validator_rejects_incomplete_shape(version_one_report, missing):
    del version_one_report[missing]
    before = deepcopy(version_one_report)

    with pytest.raises(ValueError, match="Incomplete versioned report"):
        _validate_v1(version_one_report)

    assert version_one_report == before


def test_v1_validator_rejects_extra_fields_before_value_validation(version_one_report):
    version_one_report.update(extra="Not allowed", message=None)

    with pytest.raises(ValueError, match="Incomplete versioned report"):
        _validate_v1(version_one_report)


@pytest.mark.parametrize("updates,expected", [
    ({"channel": None}, "Invalid report channel."),
    ({"message": " "}, "Invalid report message."),
    ({"sender": 1}, "Invalid report metadata."),
    ({"link": False}, "Invalid report metadata."),
    ({"has_link": 0}, "Invalid reported action."),
    ({"downloaded": None}, "Invalid reported action."),
    ({"submitted_category": "email"}, "Invalid submitted category."),
    ({"ai": None}, "Invalid stored AI findings."),
])
def test_v1_validator_preserves_known_input_field_errors(version_one_report, updates, expected):
    version_one_report.update(updates)
    before = deepcopy(version_one_report)

    with pytest.raises(ValueError) as caught:
        _validate_v1(version_one_report)

    assert str(caught.value) == expected
    assert version_one_report == before


@pytest.mark.parametrize("updates,expected", [
    ({"extra": True}, "Invalid stored AI findings."),
    ({"credential_request": 1}, "Invalid stored AI finding types."),
    ({"details": None}, "Invalid stored extraction."),
    ({"details": {"emails": []}}, "Invalid stored extraction."),
    ({"details": {"emails": [], "phone_numbers": [], "ip_addresses": [], "extra": []}},
     "Invalid stored extraction."),
    ({"details": {"emails": [" "], "phone_numbers": [], "ip_addresses": []}},
     "Invalid stored text lists."),
    ({"details": {"emails": [], "phone_numbers": (), "ip_addresses": []}},
     "Invalid stored text lists."),
    ({"details": {"emails": [], "phone_numbers": [], "ip_addresses": [None]}},
     "Invalid stored text lists."),
])
def test_v1_validator_checks_exact_ai_findings_and_extraction_without_mutation(
    version_one_report, updates, expected,
):
    version_one_report["ai"].update(updates)
    before = deepcopy(version_one_report)

    with pytest.raises(ValueError) as caught:
        _validate_v1(version_one_report)

    assert str(caught.value) == expected
    assert version_one_report == before


@pytest.mark.parametrize("version", [True, 1.0, None, "1", 99])
def test_v1_leaf_keeps_version_check_as_dispatcher_precondition(version_one_report, version):
    version_one_report["schema_version"] = version
    before = deepcopy(version_one_report)

    assert _validate_v1(version_one_report) is version_one_report
    assert version_one_report == before
    with pytest.raises(ValueError, match="Unsupported report version"):
        ReportValidator().validate_stored(version_one_report)


def test_v1_validator_uses_canonical_result_without_rule_trace_opt_in(
    version_one_report, monkeypatch,
):
    validate_result = Mock(wraps=model._validate_result)
    monkeypatch.setattr(model, "_validate_result", validate_result)

    assert _validate_v1(version_one_report) is version_one_report

    validate_result.assert_called_once_with(version_one_report["result"])
    version_one_report["result"].update(
        matched_rule="Winner", trace=[{"rule_name": "Winner", "matched": True, "score": 60}],
    )
    with pytest.raises(ValueError, match="Invalid stored assessment"):
        _validate_v1(version_one_report)


def test_v1_validator_checks_result_before_extraction_list_contents(version_one_report):
    version_one_report["result"]["score"] = True
    version_one_report["ai"]["details"]["emails"] = [None]
    before = deepcopy(version_one_report)

    with pytest.raises(ValueError, match="Invalid stored score"):
        _validate_v1(version_one_report)

    assert version_one_report == before


@pytest.mark.parametrize("shape", [
    "v2", "v3_feedback", "v3_historical_exposure", "v3_identified_exposure",
])
def test_new_report_validator_is_canonical_and_preserves_supported_records(
    version_two_report, version_three_exposure, shape,
):
    record = version_two_report if shape == "v2" else version_three_exposure
    if shape == "v3_feedback":
        record = {key: record[key] for key in ("schema_version", "channel", "message", "result")}
    if shape in {"v3_feedback", "v3_identified_exposure"}:
        record["assessment_id"] = " stable original ID "
    record["result"].update(
        matched_rule="Winner", trace=[{"rule_name": "Winner", "matched": True, "score": 60}],
    )
    before = deepcopy(record)

    assert ReportValidator.validate_new is _validate_new
    assert ReportValidator().validate_new is _validate_new
    assert _validate_new(record) is record
    assert ReportValidator.validate_new(record) is record
    assert ReportValidator().validate_new(record) is record
    assert record == before


@pytest.mark.parametrize("record", [None, [], "report", 3, False])
def test_new_report_validator_checks_root_before_version(record):
    with pytest.raises(ValueError) as caught:
        _validate_new(record)

    assert str(caught.value) == "New reports must be objects."


@pytest.mark.parametrize("version", [None, True, False, 2.0, 3.0, "3", 1, 4])
def test_new_report_validator_rejects_unsupported_versions_before_body_validation(version):
    record = {"schema_version": version, "message": None}
    before = deepcopy(record)

    with pytest.raises(ValueError) as caught:
        _validate_new(record)

    assert str(caught.value) == "Unsupported new report version."
    assert record == before


def test_new_report_validator_does_not_infer_a_missing_schema_version():
    record = {"channel": "chat", "message": "Historical input"}
    before = deepcopy(record)

    with pytest.raises(ValueError, match="Unsupported new report version"):
        _validate_new(record)

    assert record == before and "schema_version" not in record


@pytest.mark.parametrize("version", [2, 3])
def test_new_report_validator_dispatches_only_to_corresponding_canonical_validator(
    version_two_report, version_three_exposure, monkeypatch, version,
):
    v2 = Mock(wraps=model._validate_v2)
    v3 = Mock(wraps=model._validate_v3)
    monkeypatch.setattr(model, "_validate_v2", v2)
    monkeypatch.setattr(model, "_validate_v3", v3)
    record = version_two_report if version == 2 else version_three_exposure

    assert _validate_new(record) is record

    expected, other = (v2, v3) if version == 2 else (v3, v2)
    expected.assert_called_once_with(record)
    other.assert_not_called()


@pytest.mark.parametrize("version", [2, 3])
def test_new_report_validator_preserves_nested_validation_errors_without_mutation(
    version_two_report, version_three_exposure, version,
):
    record = version_two_report if version == 2 else version_three_exposure
    record["result"]["score"] = True
    before = deepcopy(record)

    with pytest.raises(ValueError) as caught:
        _validate_new(record)

    assert str(caught.value) == "Invalid stored score."
    assert record == before


@pytest.mark.parametrize("layout", [
    "partial_legacy", "summary", "v1", "v2", "v3_feedback",
    "v3_historical_exposure", "v3_identified_exposure",
])
def test_stored_report_validator_is_canonical_and_preserves_all_supported_layouts(
    summary_report, version_one_report, version_two_report, version_three_exposure, layout,
):
    if layout == "partial_legacy":
        record = {"message": None, "unknown_extra": {"original": [False, None, " "]}}
    elif layout == "summary":
        record = summary_report
    elif layout == "v1":
        record = version_one_report
    elif layout == "v2":
        record = version_two_report
    else:
        record = version_three_exposure
        if layout == "v3_feedback":
            record = {
                key: record[key] for key in ("schema_version", "channel", "message", "result")
            }
        if layout != "v3_historical_exposure":
            record["assessment_id"] = " preserved original ID "
    before = deepcopy(record)

    assert ReportValidator.validate_stored is _validate_stored
    assert ReportValidator().validate_stored is _validate_stored
    assert _validate_stored(record) is record
    assert ReportValidator.validate_stored(record) is record
    assert ReportValidator().validate_stored(record) is record
    assert record == before
    assert ("schema_version" in record) is ("schema_version" in before)
    assert ("assessment_id" in record) is ("assessment_id" in before)
    assert data_validator.REPORT_FIELDS is REPORT_FIELDS


@pytest.mark.parametrize("record", [None, [], "history", 3])
def test_stored_report_validator_checks_root_before_any_dispatch(record):
    with pytest.raises(ValueError) as caught:
        _validate_stored(record)

    assert str(caught.value) == "Stored reports must be objects."


@pytest.mark.parametrize("version", [None, True, False, 1.0, 2.0, 3.0, "1", 0, 4])
def test_stored_report_validator_rejects_explicit_bad_versions_before_payload_validation(version):
    record = {"schema_version": version, "message": 1, "result": None}
    before = deepcopy(record)

    with pytest.raises(ValueError) as caught:
        _validate_stored(record)

    assert str(caught.value) == "Unsupported report version."
    assert record == before


def test_stored_report_validator_distinguishes_exact_summary_from_permissive_legacy(summary_report):
    summary_report["score"] = 60.5
    with pytest.raises(ValueError, match="Invalid stored score"):
        _validate_stored(summary_report)
    summary_report["unknown_extra"] = {"unchanged": [None]}
    before = deepcopy(summary_report)

    assert _validate_stored(summary_report) is summary_report

    assert summary_report == before
    assert summary_report["score"] == 60.5


@pytest.mark.parametrize("version", [1, 2, 3])
def test_stored_report_validator_selects_corresponding_canonical_schema_once(
    version_one_report, version_two_report, version_three_exposure, monkeypatch, version,
):
    records = {1: version_one_report, 2: version_two_report, 3: version_three_exposure}
    validators = {
        1: Mock(wraps=model._validate_v1),
        2: Mock(wraps=model._validate_v2),
        3: Mock(wraps=model._validate_v3),
    }
    for candidate, validator in validators.items():
        monkeypatch.setattr(model, f"_validate_v{candidate}", validator)

    assert _validate_stored(records[version]) is records[version]

    validators[version].assert_called_once_with(records[version])
    assert sum(validator.call_count for validator in validators.values()) == 1


def test_stored_report_validator_preserves_nested_failures_without_mutation(version_one_report):
    version_one_report["result"]["score"] = True
    before = deepcopy(version_one_report)

    with pytest.raises(ValueError) as caught:
        _validate_stored(version_one_report)

    assert str(caught.value) == "Invalid stored score."
    assert version_one_report == before
