"""Immutable JSON ownership for the report model foundation."""

import math
from collections import UserDict
from copy import deepcopy
from types import MappingProxyType
from unittest.mock import Mock

import pytest

from phishreport import model
from phishreport.data.validator import ReportValidator
from phishreport.model import (
    SCHEMA_VERSION,
    SCHEMA_VERSION_KEY,
    _freeze_json,
    _validate_result,
    _validate_rule_trace,
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
