"""Immutable JSON ownership for the report model foundation."""

import json
import math
from collections import UserDict
from copy import deepcopy
from dataclasses import FrozenInstanceError
from types import MappingProxyType
from unittest.mock import Mock

import pytest

from phishreport import model
from phishreport.data import validator as data_validator
from phishreport.data.json_storage import JsonReportStorage
from phishreport.data.sqlite_storage import SqliteReportStorage
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


def test_exposure_answers_defaults_preserve_unknown_as_distinct_from_confirmed_flags():
    answers = model.ExposureAnswers()

    assert answers.clicked is None
    assert answers.downloaded is None
    assert answers.submitted_category is None
    assert answers.disclosure_answered is None
    assert answers != model.ExposureAnswers(False, False, None, False)
    assert answers != model.ExposureAnswers(True, True, None, True)


@pytest.mark.parametrize("clicked,downloaded,category,disclosure_answered", [
    (None, None, None, None),
    (False, False, None, False),
    (True, True, "password", True),
    (None, False, "otp", None),
    (True, None, " Legacy category ", False),
    (False, True, "", None),
    (None, True, " ", True),
])
def test_exposure_answers_preserves_independent_nullable_flags_and_historical_categories(
    clicked, downloaded, disclosure_answered, category,
):
    answers = model.ExposureAnswers(clicked, downloaded, category, disclosure_answered)

    assert answers.clicked is clicked
    assert answers.downloaded is downloaded
    assert answers.submitted_category is category
    assert answers.disclosure_answered is disclosure_answered


def test_exposure_answers_is_frozen_and_slotted():
    answers = model.ExposureAnswers(False, True, "password", None)

    assert not hasattr(answers, "__dict__")
    with pytest.raises(FrozenInstanceError):
        answers.clicked = True
    with pytest.raises(FrozenInstanceError):
        del answers.submitted_category


@pytest.mark.parametrize("field", ["clicked", "downloaded", "disclosure_answered"])
@pytest.mark.parametrize("value", [
    0, 1, 0.0, 1.0, "private", [], {}, (), {"private"}, bytearray(b"private"),
])
def test_exposure_answers_rejects_boolean_lookalikes_and_collections(field, value):
    with pytest.raises(ValueError) as caught:
        model.ExposureAnswers(**{field: value})

    assert str(caught.value) == "Invalid exposure answer flag."


@pytest.mark.parametrize("value", [
    False, True, 0, 1.0, [], {}, (), {"private"}, bytearray(b"private"), b"private",
])
def test_exposure_answers_rejects_non_string_categories_with_safe_errors(value):
    with pytest.raises(ValueError) as caught:
        model.ExposureAnswers(submitted_category=value)

    assert str(caught.value) == "Invalid exposure answer category."


def test_exposure_answers_never_formats_rejected_values():
    class Unprintable:
        def __repr__(self):
            raise AssertionError("Private value formatted")

        def __str__(self):
            raise AssertionError("Private value formatted")

    for field in ("clicked", "downloaded", "submitted_category", "disclosure_answered"):
        with pytest.raises(ValueError) as caught:
            model.ExposureAnswers(**{field: Unprintable()})
        assert "Private" not in str(caught.value)


def test_assessment_result_requires_nullable_score_and_priority_and_is_frozen_slotted():
    result = model.AssessmentResult(score=None, priority=None)

    assert result.score is None and result.priority is None
    assert result.reasons == result.checklist == result.trace == ()
    assert result.matched_rule is None
    assert not hasattr(result, "__dict__")
    with pytest.raises(FrozenInstanceError):
        result.score = 60
    with pytest.raises(FrozenInstanceError):
        del result.priority
    with pytest.raises(TypeError):
        model.AssessmentResult(priority=None)
    with pytest.raises(TypeError):
        model.AssessmentResult(score=None)


@pytest.mark.parametrize("score,priority", [
    (None, None), (-1000, "historical label"), (1000, ""), (60.5, " mixed Case "),
])
def test_assessment_result_preserves_legacy_scalars_and_blank_guidance(score, priority):
    result = model.AssessmentResult(score, priority, ["", " ", "Reason"], ("", "Check"))

    assert result.score is score and result.priority is priority
    assert result.reasons == ("", " ", "Reason")
    assert result.checklist == ("", "Check")


@pytest.mark.parametrize("matched_rule", [None, "", " Historical rule "])
def test_assessment_result_empty_trace_preserves_optional_legacy_matched_rule(matched_rule):
    result = model.AssessmentResult(None, None, matched_rule=matched_rule)
    assert result.matched_rule is matched_rule


def test_assessment_result_owns_guidance_and_trace_lists_without_mutating_inputs():
    reasons, checklist = ["Reason"], ["Check"]
    trace = [model.RuleTrace("Skip", False), model.RuleTrace("Winner", True, 60)]
    result = model.AssessmentResult(60, "HIGH", reasons, checklist, "Winner", trace)

    assert reasons == ["Reason"] and checklist == ["Check"]
    assert trace == [model.RuleTrace("Skip", False), model.RuleTrace("Winner", True, 60)]
    reasons[0] = "changed"
    checklist.clear()
    trace.clear()
    assert result.reasons == ("Reason",) and result.checklist == ("Check",)
    assert result.trace == (model.RuleTrace("Skip", False), model.RuleTrace("Winner", True, 60))


@pytest.mark.parametrize("field,value", [
    ("score", True), ("score", "60"), ("score", float("nan")),
    ("score", float("inf")), ("score", float("-inf")),
    ("score", type("ScoreSubclass", (int,), {})(60)),
    ("priority", 60), ("priority", []), ("matched_rule", 60), ("matched_rule", []),
    ("reasons", None), ("reasons", "private reason"), ("reasons", {"private reason"}),
    ("reasons", iter(["private reason"])), ("reasons", [None]),
    ("checklist", None), ("checklist", "private check"), ("checklist", [False]),
    ("checklist", {"private check"}), ("checklist", iter(["private check"])),
    ("trace", None), ("trace", "private trace"), ("trace", iter([])),
    ("trace", [{}]), ("trace", [None]),
])
def test_assessment_result_rejects_invalid_field_types_with_safe_errors(field, value):
    arguments = {"score": None, "priority": None, field: value}
    with pytest.raises(ValueError) as caught:
        model.AssessmentResult(**arguments)
    assert "private" not in str(caught.value)


@pytest.mark.parametrize("trace,score,matched_rule", [
    ([model.RuleTrace("", True, 60)], 60, "Winner"),
    ([model.RuleTrace([], True, 60)], 60, "Winner"),
    ([model.RuleTrace("Winner", [], 60)], 60, "Winner"),
    ([model.RuleTrace("Winner", 1, 60)], 60, "Winner"),
    ([model.RuleTrace("Winner", True, [])], 60, "Winner"),
    ([model.RuleTrace("Winner", True, True)], 60, "Winner"),
    ([model.RuleTrace("Winner", True, 60.0)], 60, "Winner"),
    ([model.RuleTrace("Winner", True, 101)], 101, "Winner"),
    ([model.RuleTrace("Skip", False, 0), model.RuleTrace("Winner", True, 60)], 60, "Winner"),
    ([model.RuleTrace("Earlier", True, 60), model.RuleTrace("Winner", True, 60)], 60, "Winner"),
    ([model.RuleTrace("Winner", False)], 60, "Winner"),
    ([model.RuleTrace("Winner", True, 60)], 61, "Winner"),
    ([model.RuleTrace("Winner", True, 60)], 60, "Other"),
    ([model.RuleTrace("Winner", True, 60)], None, "Winner"),
    ([model.RuleTrace("Winner", True, 60)], 60, None),
    ([model.RuleTrace("Winner", True, 60)], 60, ""),
])
def test_assessment_result_reuses_canonical_trace_rules_without_input_mutation(
    trace, score, matched_rule,
):
    before = deepcopy([step.as_dict() for step in trace])
    with pytest.raises(ValueError) as canonical_error:
        _validate_rule_trace({"score": score, "matched_rule": matched_rule, "trace": before})
    with pytest.raises(ValueError) as caught:
        model.AssessmentResult(score, "legacy", matched_rule=matched_rule, trace=trace)
    assert str(caught.value) == str(canonical_error.value)
    assert [step.as_dict() for step in trace] == before


def test_assessment_result_never_formats_rejected_values():
    class Unprintable:
        def __repr__(self):
            raise AssertionError("Private value formatted")

    private = Unprintable()
    for field in ("score", "priority", "matched_rule", "reasons", "checklist", "trace"):
        with pytest.raises(ValueError):
            model.AssessmentResult(**{"score": None, "priority": None, field: private})
    with pytest.raises(ValueError):
        model.AssessmentResult(
            60, "HIGH", matched_rule="Winner", trace=[model.RuleTrace(private, True, 60)],
        )


def test_rule_trace_is_the_same_canonical_class_through_existing_imports():
    from phishreport.logic import RuleTrace as PublicRuleTrace
    from phishreport.logic.rule_trace import RuleTrace as LogicRuleTrace

    assert model.RuleTrace is LogicRuleTrace is PublicRuleTrace
    assert model.RuleTrace.__module__ == "phishreport.model"


def test_rule_trace_preserves_default_score_equality_and_hash():
    trace = model.RuleTrace("Unmatched", False)

    assert trace == model.RuleTrace(rule_name="Unmatched", matched=False, score=None)
    assert len({trace, model.RuleTrace("Unmatched", False, None)}) == 1
    assert trace != model.RuleTrace("Winner", True, 60)
    assert trace.as_dict() == {"rule_name": "Unmatched", "matched": False, "score": None}


def test_rule_trace_remains_frozen_and_slotted():
    trace = model.RuleTrace("Winner", True, 60)

    with pytest.raises(FrozenInstanceError):
        trace.score = 0
    with pytest.raises(FrozenInstanceError):
        del trace.rule_name
    assert not hasattr(trace, "__dict__")
    assert trace.as_dict() == {"rule_name": "Winner", "matched": True, "score": 60}


@pytest.mark.parametrize("args,kwargs", [
    ((), {}),
    (("Winner",), {}),
    (("Winner", True, 60, "extra"), {}),
    (("Winner", True), {"unknown": 60}),
    (("Winner", True), {"rule_name": "duplicate"}),
])
def test_rule_trace_preserves_constructor_argument_errors(args, kwargs):
    with pytest.raises(TypeError):
        model.RuleTrace(*args, **kwargs)


@pytest.mark.parametrize("rule_name,matched,score", [
    ("", False, None),
    (None, "unvalidated", -1),
    ("Winner", True, True),
    ("Winner", False, 101),
])
def test_rule_trace_does_not_add_runtime_field_validation(rule_name, matched, score):
    trace = model.RuleTrace(rule_name, matched, score)

    assert trace.rule_name is rule_name
    assert trace.matched is matched
    assert trace.score is score


def test_rule_trace_serialization_returns_independent_fresh_dictionaries():
    trace = model.RuleTrace("Winner", True, 60)
    first = trace.as_dict()
    second = trace.as_dict()
    first.update(rule_name="Changed", matched=False, score=0)
    first["extra"] = "only first"

    assert first is not second
    assert second == {"rule_name": "Winner", "matched": True, "score": 60}
    assert trace.as_dict() == second
    assert (trace.rule_name, trace.matched, trace.score) == ("Winner", True, 60)


def test_canonical_rule_trace_serialization_is_accepted_by_existing_validators(
    version_two_report,
):
    version_two_report["result"].update(
        matched_rule="Winner",
        trace=[
            model.RuleTrace("Unmatched", False).as_dict(),
            model.RuleTrace("Winner", True, 60).as_dict(),
        ],
    )
    before = deepcopy(version_two_report)

    assert _validate_rule_trace(version_two_report["result"]) is None
    assert _validate_result(version_two_report["result"], allow_rule_trace=True) is None
    assert _validate_new(version_two_report) is version_two_report
    assert _validate_stored(version_two_report) is version_two_report
    assert ReportValidator.validate_new(version_two_report) is version_two_report
    assert version_two_report == before


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


def test_thaw_json_outputs_are_independent_of_source_snapshot_and_each_other():
    source = {"unknown": {"items": [{"value": "original"}]}, "answer": None, "clicked": False}
    frozen = _freeze_json(source)
    first = model._thaw_json(frozen)
    second = model._thaw_json(frozen)
    assert first == second == source
    first["unknown"]["items"][0]["value"] = "changed output"
    source["unknown"]["items"].append("changed input")
    assert second["unknown"]["items"] == [{"value": "original"}]
    assert model._thaw_json(frozen) == second
    assert second["answer"] is None and second["clicked"] is False


@pytest.mark.parametrize("value", [None, True, False, 0, -17, 2.5, " Mixed CASE\n ",
                                  float("nan"), float("inf")])
def test_thaw_json_preserves_scalar_objects_without_normalization(value):
    assert model._thaw_json(value) is value


def test_thaw_json_owns_mapping_and_sequence_inputs():
    shared = {"items": ["original"]}
    source = UserDict({"left": shared, "right": (shared,)})
    output = model._thaw_json(source)
    output["left"]["items"].append("left only")
    assert output["right"] == [{"items": ["original"]}]
    assert shared == {"items": ["original"]}
    assert type(output) is dict


@pytest.mark.parametrize("value", [object(), {1, 2}, bytearray(b"private"), {1: "private"}])
def test_thaw_json_rejects_unsupported_values_without_exposing_them(value):
    with pytest.raises(ValueError, match="JSON-compatible") as caught:
        model._thaw_json({"nested": (value,)})
    assert "private" not in str(caught.value)


def test_thaw_json_does_not_format_rejected_values():
    class Unprintable:
        def __repr__(self):
            raise AssertionError("Private value formatted")

    with pytest.raises(ValueError, match="JSON-compatible"):
        model._thaw_json(Unprintable())


@pytest.mark.parametrize("fixture_name", [
    "summary_report", "version_one_report", "version_two_report", "version_three_exposure",
])
def test_thaw_json_round_trips_valid_history_without_changing_shape(request, fixture_name):
    source = request.getfixturevalue(fixture_name)
    before = deepcopy(source)
    restored = model._thaw_json(_freeze_json(source))
    assert restored == source == before
    assert restored is not source
    assert _validate_stored(restored) is restored
    assert json.loads(json.dumps(restored)) == source


def test_thaw_json_preserves_existing_feedback_id_and_missing_legacy_fields(assessment_result):
    source = {
        "schema_version": 3, "assessment_id": " Original ID ",
        "channel": "chat", "message": " Message\n ", "result": assessment_result,
    }
    restored = model._thaw_json(_freeze_json(source))
    assert restored == source and _validate_stored(restored) is restored
    legacy = {"message": None, "unknown": {"items": [False, None, " "]}}
    restored_legacy = model._thaw_json(_freeze_json(legacy))
    assert restored_legacy == legacy
    assert "schema_version" not in restored_legacy
    assert "assessment_id" not in restored_legacy


@pytest.mark.parametrize("fixture_name", [
    "summary_report", "version_one_report", "version_two_report", "version_three_exposure",
])
def test_report_constructor_projects_supported_history_and_owns_exact_snapshot(
    request, fixture_name,
):
    source = request.getfixturevalue(fixture_name)
    before = deepcopy(source)
    report = model.Report(source)

    assert report.message == source["message"]
    assert report.channel == source["channel"]
    assert report.result.score == 60
    assert model._thaw_json(report._payload) == before == source
    assert report.assessment_id == source.get("assessment_id")
    assert report.schema_version == source.get("schema_version")


def test_report_constructor_isolates_source_aliases_and_freezes_projected_values():
    source = UserDict({
        "message": " Original\n ", "assessment_id": " ID ",
        "result": {"reasons": ["Reason"], "priority": " Historical "},
        "details": {"emails": ["a@example.test"]},
        "unknown": {"items": [None, False]},
    })
    report = model.Report(source)
    source["message"] = "changed"
    source["result"]["reasons"].clear()
    source["details"]["emails"].append("later@example.test")
    source["unknown"]["items"].clear()

    assert report.message == " Original\n " and report.assessment_id == " ID "
    assert report.result.reasons == ("Reason",)
    assert report.emails == ("a@example.test",)
    assert report._payload["unknown"]["items"] == (None, False)
    assert report._payload["message"] == report.message
    assert report._payload["result"]["reasons"] == report.result.reasons
    assert not hasattr(report, "__dict__") and not hasattr(report, "source")
    with pytest.raises(FrozenInstanceError):
        report.message = "changed"
    with pytest.raises(FrozenInstanceError):
        report.result.priority = "changed"
    with pytest.raises(TypeError):
        report._payload["unknown"]["items"] = ()


def test_report_constructor_projects_partial_malformed_summary_without_normalizing_snapshot():
    source = {
        "schema_version": True, "assessment_id": 1, "channel": [], "message": None,
        "sender": "", "link": " URL ", "file_name": {}, "has_link": 1, "has_file": False,
        "score": True, "priority": [], "reasons": ["", 1, "reason", "reason", None],
        "checklist": "not a sequence", "details": {"emails": ["", False, "a", "a"]},
        "unknown": [None, {"legacy": " retained "}],
    }
    before = deepcopy(source)
    report = model.Report(source)
    assert report.schema_version is report.assessment_id is report.channel is None
    assert report.message is report.file_name is report.has_link is None
    assert report.sender == "" and report.link == " URL " and report.has_file is False
    assert report.result == model.AssessmentResult(None, None, ("", "reason", "reason"))
    assert report.emails == ("", "a", "a")
    assert report.phone_numbers == report.ip_addresses == ()
    assert model._thaw_json(report._payload) == source == before
    assert "assessment_id" in report._payload
    assert model.Report({}).result is None
    assert model.Report({}).exposure is None


@pytest.mark.parametrize("nested,expected_score,expected_priority", [
    ({"score": 9}, 9, None), ({"extra": True}, None, None),
    ({}, 60, "root"), (None, 60, "root"), (["invalid"], 60, "root"),
])
def test_report_constructor_selects_one_result_source_without_merging(
    nested, expected_score, expected_priority,
):
    report = model.Report({"result": nested, "score": 60, "priority": "root"})
    if nested == {"extra": True}:
        assert report.result is None
    else:
        assert report.result.score == expected_score
        assert report.result.priority == expected_priority


@pytest.mark.parametrize("score,expected", [
    (60.5, 60.5), (-400, -400), (1000, 1000), (True, None), ("60", None),
    (float("nan"), None), (float("inf"), None), (float("-inf"), None),
])
def test_report_constructor_preserves_historical_finite_scores_and_hides_invalid_scores(
    score, expected,
):
    report = model.Report({"score": score, "priority": ""})
    assert report.result.score == expected
    assert report.result.priority == ""
    assert report._payload["score"] is score


@pytest.mark.parametrize("updates,valid", [
    ({}, True), ({"matched_rule": "Other"}, False), ({"score": None}, False),
    ({"trace": [{"rule_name": "Winner", "matched": True}]}, False),
    ({"trace": [{"rule_name": "Skip", "matched": False, "score": 0},
                {"rule_name": "Winner", "matched": True, "score": 60}]}, False),
    ({"trace": "invalid"}, False), ({"trace": []}, False),
])
def test_report_constructor_accepts_only_wholly_canonical_rule_traces(updates, valid):
    result = {"score": 60, "matched_rule": "Winner", "trace": [
        {"rule_name": "Skip", "matched": False, "score": None},
        {"rule_name": "Winner", "matched": True, "score": 60},
    ]}
    result.update(updates)
    report = model.Report({"result": result})
    assert report.result.matched_rule == result["matched_rule"]
    assert report.result.trace == ((model.RuleTrace("Skip", False),
                                    model.RuleTrace("Winner", True, 60)) if valid else ())
    assert model._thaw_json(report._payload)["result"] == result


@pytest.mark.parametrize("missing", ["score", "matched_rule", "trace"])
def test_report_constructor_does_not_infer_missing_trace_fields(missing):
    result = {"score": 60, "matched_rule": "Winner", "trace": [
        {"rule_name": "Winner", "matched": True, "score": 60},
    ]}
    del result[missing]
    assert model.Report({"result": result}).result.trace == ()


@pytest.mark.parametrize("nested", [None, [], "invalid"])
def test_report_constructor_v3_missing_or_malformed_exposure_never_uses_root(nested):
    source = {"schema_version": 3, "clicked": True, "submitted_category": "root"}
    assert model.Report(source).exposure is None
    source["exposure"] = nested
    report = model.Report(source)
    assert report.exposure is None and report.has_nested_exposure is False


@pytest.mark.parametrize("answered", [None, False, True])
def test_report_constructor_v3_preserves_nested_categories_and_confirmation_independently(answered):
    report = model.Report({"schema_version": 3, "clicked": True, "exposure": {
        "clicked": None, "downloaded": False, "submitted_category": " historical ",
        "disclosure_answered": answered,
    }})
    assert report.has_nested_exposure is True
    assert report.exposure == model.ExposureAnswers(None, False, " historical ", answered)
    empty = model.Report({"schema_version": 3, "clicked": True, "exposure": {}})
    assert empty.has_nested_exposure is True
    assert empty.exposure == model.ExposureAnswers()


@pytest.mark.parametrize("version", [None, 1, 2, 3.0, True, 99])
def test_report_constructor_historical_exposure_uses_only_root_and_exact_boolean_flags(version):
    source = {"schema_version": version, "clicked": 1, "downloaded": False,
              "submitted_category": "", "disclosure_answered": "yes",
              "exposure": {"clicked": True, "submitted_category": "nested"}}
    report = model.Report(source)
    assert report.exposure == model.ExposureAnswers(None, False, "", None)
    assert report.has_nested_exposure is False
    assert model.Report({"schema_version": version, "exposure": {}}).exposure is None


@pytest.mark.parametrize("root_details,expected", [
    ({}, ()), ({"emails": ["root", 1, "", "root"]}, ("root", "", "root")),
    (None, ("ai", "", "ai")), ([], ("ai", "", "ai")),
])
def test_report_constructor_selects_root_details_even_when_empty_without_merging(
    root_details, expected,
):
    report = model.Report({"details": root_details, "ai": {"details": {
        "emails": ["ai", False, "", "ai"], "phone_numbers": ["123"],
        "ip_addresses": "not a list",
    }}})
    assert report.emails == expected
    assert report.phone_numbers == (() if isinstance(root_details, dict) else ("123",))
    assert report.ip_addresses == ()


@pytest.mark.parametrize("source", [None, [], "private", 1, False])
def test_report_constructor_rejects_non_mapping_roots_with_safe_fixed_error(source):
    with pytest.raises(ValueError) as caught:
        model.Report(source)
    assert str(caught.value) == "Report source must be an object."


def test_report_constructor_rejects_unsupported_values_even_in_unused_fields_without_formatting():
    class Unprintable:
        def __repr__(self):
            raise AssertionError("Private value formatted")

    for source in (Unprintable(), {"unused": Unprintable()}, {"details": {1: "private"}}):
        with pytest.raises(ValueError) as caught:
            model.Report(source)
        assert "Private" not in str(caught.value)


@pytest.mark.parametrize("layout", [
    "partial_legacy", "summary", "v1", "v2", "v3_feedback",
    "v3_historical_exposure", "v3_identified_exposure",
])
def test_report_from_legacy_preserves_all_supported_layouts_without_inventing_fields(
    summary_report, version_one_report, version_two_report, version_three_exposure, layout,
):
    records = {
        "partial_legacy": {"message": None, "extra": {"items": [False, None, " "]}},
        "summary": summary_report, "v1": version_one_report, "v2": version_two_report,
        "v3_feedback": {
            "schema_version": 3, "assessment_id": " Original ID ",
            "channel": "chat", "message": " Original\n ", "result": {"score": 60,
            "priority": "MEDIUM", "reasons": [], "checklist": []},
        },
        "v3_historical_exposure": version_three_exposure,
        "v3_identified_exposure": {**version_three_exposure, "assessment_id": " Existing ID "},
    }
    source = records[layout]
    before = deepcopy(source)

    report = model.Report.from_legacy(source)

    assert isinstance(report, model.Report)
    assert model._thaw_json(report._payload) == before == source
    assert report.schema_version == before.get("schema_version")
    assert report.assessment_id == before.get("assessment_id")
    assert ("schema_version" in report._payload) is ("schema_version" in before)
    assert ("assessment_id" in report._payload) is ("assessment_id" in before)
    if layout in {"v3_historical_exposure", "v3_identified_exposure"}:
        assert report.exposure == model.ExposureAnswers(None, False, None, False)


def test_report_from_legacy_owns_snapshot_and_preserves_raw_legacy_values():
    source = {
        "message": " Original\n ", "sender": None, "clicked": False,
        "score": 160.5, "priority": " Historical ", "reasons": ["", " ", "same", "same"],
        "details": {"emails": ["", " original "]},
        "unknown": {"items": [None, False, {"text": " unchanged "}]},
    }
    before = deepcopy(source)
    report = model.Report.from_legacy(source)
    assert source == before
    source["message"] = "changed"
    source["reasons"].clear()
    source["details"]["emails"].clear()
    source["unknown"]["items"][2]["text"] = "changed"

    assert model._thaw_json(report._payload) == before
    assert report.message == " Original\n "
    assert report.result.score == 160.5 and type(report.result.score) is float
    assert report.result.priority == " Historical "
    assert report.result.reasons == ("", " ", "same", "same")
    assert report.emails == ("", " original ")
    assert report.exposure.clicked is False
    assert report.sender is report.schema_version is report.assessment_id is None


@pytest.mark.parametrize("source", [
    {"schema_version": True}, {"schema_version": 2.0}, {"schema_version": None},
    {"schema_version": 2, "channel": "chat", "message": "message"},
    {"schema_version": 3, "channel": "chat", "message": "message", "result": {}},
    {"message": 1}, {"score": True}, {"result": {"reasons": [None]}},
    {"details": {"emails": "invalid"}},
])
def test_report_from_legacy_rejects_malformed_history_before_tolerant_projection(
    source, monkeypatch,
):
    before = deepcopy(source)
    assert model._thaw_json(model.Report(source)._payload) == before

    def forbidden_projection(self, source):
        pytest.fail("Malformed stored history reached the tolerant constructor")

    monkeypatch.setattr(model.Report, "__post_init__", forbidden_projection)
    with pytest.raises(ValueError):
        model.Report.from_legacy(source)
    assert source == before


@pytest.mark.parametrize("source", [None, [], "history", 3, UserDict({"message": "text"})])
def test_report_from_legacy_rejects_non_dictionary_roots(source):
    with pytest.raises(ValueError, match="Stored reports must be objects"):
        model.Report.from_legacy(source)


def test_report_from_legacy_accepts_unversioned_v2_shaped_data_without_inference(
    version_two_report,
):
    del version_two_report["schema_version"]
    report = model.Report.from_legacy(version_two_report)
    assert model._thaw_json(report._payload) == version_two_report
    assert report.schema_version is report.assessment_id is None
    assert report.result.score == 60


def test_report_from_legacy_propagates_canonical_validation_exception_identity(monkeypatch):
    error = ValueError("Canonical validation failure")

    def reject(record):
        raise error

    monkeypatch.setattr(model, "_validate_stored", reject)
    with pytest.raises(ValueError) as caught:
        model.Report.from_legacy({})
    assert caught.value is error


def test_report_from_legacy_constructs_requested_subclass():
    class HistoricalReport(model.Report):
        pass

    report = HistoricalReport.from_legacy({"message": " Original "})
    assert type(report) is HistoricalReport
    assert report.message == " Original "


@pytest.mark.parametrize("layout", [
    "partial_legacy", "summary", "v1", "v2", "v3_feedback",
    "v3_historical_exposure", "v3_identified_exposure",
])
@pytest.mark.parametrize("storage_type", [JsonReportStorage, SqliteReportStorage])
def test_report_to_dict_preserves_history_through_json_and_real_storage(
    summary_report, version_one_report, version_two_report, version_three_exposure,
    layout, storage_type, tmp_path,
):
    records = {
        "partial_legacy": {"message": None, "extra": {"items": [False, None, " "]}},
        "summary": summary_report, "v1": version_one_report, "v2": version_two_report,
        "v3_feedback": {
            "schema_version": 3, "assessment_id": " Original ID ",
            "channel": "chat", "message": " Original\n ", "result": {
                "score": 60, "priority": "MEDIUM", "reasons": [], "checklist": [],
            },
        },
        "v3_historical_exposure": version_three_exposure,
        "v3_identified_exposure": {**version_three_exposure, "assessment_id": " Existing ID "},
    }
    source = records[layout]
    if layout in {"v2", "v3_feedback"}:
        source["result"].update(matched_rule="Winner", trace=[
            {"rule_name": "Skip", "matched": False, "score": None},
            {"rule_name": "Winner", "matched": True, "score": 60},
        ])
    before = deepcopy(source)
    report = model.Report.from_legacy(source)

    output = report.to_dict()

    assert type(output) is dict
    assert output == source == before
    assert output is not source
    assert json.loads(json.dumps(output, allow_nan=False)) == before
    assert _validate_stored(output) is output
    for key in ("schema_version", "assessment_id", "exposure", "sender"):
        assert (key in output) is (key in before)
    storage = storage_type(tmp_path / "history")
    storage.write_records([output])
    restored = storage.read_records()
    assert restored == [before]
    assert model.Report.from_legacy(restored[0]).to_dict() == before


def test_report_to_dict_returns_fresh_nested_containers_isolated_from_source_and_model():
    source = {
        "message": " Original\n ", "assessment_id": " ID ", "sender": None,
        "clicked": False, "reasons": ["", "same", "same"],
        "unknown": {"items": [{"values": [None, False, " unchanged "]}]},
    }
    before = deepcopy(source)
    report = model.Report.from_legacy(source)
    first, second = report.to_dict(), report.to_dict()

    first["unknown"]["items"][0]["values"].append("first only")
    first["unknown"]["items"].append({"new": []})
    first["unknown"]["added"] = True
    first["reasons"].clear()
    first["assessment_id"] = "changed output"
    assert source == before
    source["unknown"]["items"][0]["values"].clear()
    source["reasons"].append("source only")
    source["message"] = "changed source"

    assert first is not second
    assert second == report.to_dict() == before
    assert report.message == " Original\n " and report.assessment_id == " ID "
    assert report.result.reasons == ("", "same", "same")
    assert report._payload["unknown"]["items"][0]["values"] == (None, False, " unchanged ")
    second["unknown"]["items"][0]["values"][0] = "second only"
    assert report.to_dict() == before


def test_report_to_dict_preserves_malformed_raw_values_instead_of_filtered_attributes(monkeypatch):
    source = {
        "schema_version": 3, "assessment_id": 1, "channel": [], "message": None,
        "has_link": 1, "result": {
            "score": True, "priority": [], "reasons": ["", None, False, "reason"],
            "checklist": "not a list", "matched_rule": "Winner",
            "trace": [{"rule_name": "Winner", "matched": "yes", "score": 60}],
        },
        "exposure": {"clicked": 1, "downloaded": False,
                     "submitted_category": ["password"], "disclosure_answered": "yes"},
        "details": {"emails": ["a", None, "", False]},
        "unknown": {"items": [None, False, {"text": " retained "}]},
    }
    before = deepcopy(source)
    report = model.Report(source)
    assert report.assessment_id is report.channel is report.has_link is None
    assert report.result.reasons == ("", "reason") and report.result.trace == ()
    assert report.exposure == model.ExposureAnswers(None, False, None, None)
    assert report.emails == ("a", "")

    def forbidden_validation(*args, **kwargs):
        pytest.fail("Serialization must not validate or project stored history again")

    for name in ("_validate_stored", "_validate_result", "_validate_rule_trace"):
        monkeypatch.setattr(model, name, forbidden_validation)
    output = report.to_dict()
    assert output == source == before
    assert json.loads(json.dumps(output, allow_nan=False)) == before


def test_report_to_dict_converts_owned_mapping_and_tuple_graphs_to_plain_json_containers():
    source = UserDict({"unknown": (UserDict({"items": (None, False, " Text ")}),)})
    output = model.Report(source).to_dict()

    assert type(output) is dict and type(output["unknown"]) is list
    assert type(output["unknown"][0]) is dict
    assert type(output["unknown"][0]["items"]) is list
    assert output == {"unknown": [{"items": [None, False, " Text "]}]}
    assert json.loads(json.dumps(output)) == output


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_report_to_dict_keeps_nonfinite_raw_extras_without_normalizing_them(value):
    source = {"unknown": {"items": [value]}, "score": value}
    report = model.Report(source)

    output = report.to_dict()

    assert report.result.score is None
    assert output["score"] is value and output["unknown"]["items"][0] is value
    assert math.isnan(output["score"]) if math.isnan(value) else output["score"] == value


@pytest.mark.parametrize("with_trace", [False, True])
@pytest.mark.parametrize("storage_type", [JsonReportStorage, SqliteReportStorage])
def test_report_from_assessment_preserves_plain_v3_through_real_storage(
    with_trace, storage_type, tmp_path,
):
    record = {
        "channel": " chat ", "message": " Original\n ", "sender": "private",
        "has_link": True, "link": "private", "has_file": True,
        "file_name": "private", "ai": {"suspicious": True}, "clicked": True,
        "exposure": {"clicked": True}, "schema_version": 1,
    }
    result = {
        "assessment_id": " Existing ID ", "score": 60, "priority": "MEDIUM",
        "reasons": [" Original reason "], "checklist": [],
    }
    expected = {
        "schema_version": 3, "assessment_id": " Existing ID ",
        "channel": " chat ", "message": " Original\n ", "result": {
            "score": 60, "priority": "MEDIUM",
            "reasons": [" Original reason "], "checklist": [],
        },
    }
    if with_trace:
        trace = [
            {"rule_name": "Skip", "matched": False, "score": None},
            {"rule_name": "Winner", "matched": True, "score": 60},
        ]
        result.update(matched_rule="Winner", trace=deepcopy(trace))
        expected["result"].update(matched_rule="Winner", trace=trace)
    before = deepcopy((record, result))

    report = model.Report.from_assessment(record, result)

    assert (record, result) == before
    assert report.to_dict() == expected
    assert report.assessment_id == " Existing ID "
    assert report.sender is report.exposure is report.has_link is None
    record["message"] = "changed"
    result["reasons"].clear()
    if with_trace:
        result["trace"][-1]["rule_name"] = "changed"
    output = report.to_dict()
    assert output == expected
    assert json.loads(json.dumps(output, allow_nan=False)) == expected
    assert _validate_new(output) is output
    storage = storage_type(tmp_path / "history")
    storage.write_records([output])
    restored = storage.read_records()
    assert restored == [expected]
    assert model.Report.from_legacy(restored[0]).to_dict() == expected


@pytest.mark.parametrize("result", [
    {}, {"assessment_id": None}, {"assessment_id": True},
    {"assessment_id": ""}, {"assessment_id": " \n "},
])
def test_report_from_assessment_requires_existing_id_before_reading_record(result):
    before = deepcopy(result)
    with pytest.raises(ValueError) as caught:
        model.Report.from_assessment({}, result)
    assert str(caught.value) == "Assessment result is missing its identifier."
    assert result == before


@pytest.mark.parametrize("record,changes,omitted,error", [
    ({"channel": "chat", "message": "text"}, {"assessment_id": "x" * 101}, None,
     "Invalid assessment identifier."),
    ({"channel": " ", "message": "text"}, {}, None, "Invalid report text: channel"),
    ({"channel": "chat", "message": None}, {}, None, "Invalid report text: message"),
    ({"channel": "chat", "message": "text"}, {"score": True}, None,
     "Invalid stored score."),
    ({"channel": "chat", "message": "text"}, {}, "checklist", "Invalid stored assessment."),
    ({"channel": "chat", "message": "text"}, {"reasons": [" "]}, None,
     "Invalid stored text lists."),
    ({"channel": "chat", "message": "text"}, {"extra": True}, None,
     "Invalid stored assessment."),
    ({"channel": "chat", "message": "text"}, {"matched_rule": "Winner"}, None,
     "Invalid stored assessment."),
    ({"channel": "chat", "message": "text"}, {
        "matched_rule": "Winner",
        "trace": [{"rule_name": "Winner", "matched": True, "score": 99}],
    }, None, "Stored rule trace does not match its assessment."),
])
def test_report_from_assessment_validates_before_tolerant_constructor(
    record, changes, omitted, error, monkeypatch,
):
    result = {
        "assessment_id": "id", "score": 60, "priority": "MEDIUM",
        "reasons": [], "checklist": [], **changes,
    }
    if omitted:
        del result[omitted]
    before = deepcopy((record, result))

    def forbidden_constructor(self, source):
        pytest.fail("Invalid assessment reached the tolerant constructor")

    monkeypatch.setattr(model.Report, "__post_init__", forbidden_constructor)
    with pytest.raises(ValueError) as caught:
        model.Report.from_assessment(record, result)
    assert str(caught.value) == error
    assert (record, result) == before


def test_report_from_assessment_uses_new_validation_and_preserves_error_identity(monkeypatch):
    error = ValueError("Canonical new-report rejection")
    seen = []

    def reject(payload):
        seen.append(deepcopy(payload))
        raise error

    def forbidden(*args):
        pytest.fail("New assessments must not use stored validation or construct on failure")

    monkeypatch.setattr(model, "_validate_new", reject)
    monkeypatch.setattr(model, "_validate_stored", forbidden)
    monkeypatch.setattr(model.Report, "__post_init__", forbidden)
    with pytest.raises(ValueError) as caught:
        model.Report.from_assessment({"channel": "chat", "message": "text"}, {
            "assessment_id": " ID ", "score": 60, "priority": "MEDIUM",
            "reasons": [], "checklist": [],
        })
    assert caught.value is error
    assert seen == [{
        "schema_version": 3, "assessment_id": " ID ", "channel": "chat",
        "message": "text", "result": {
            "score": 60, "priority": "MEDIUM", "reasons": [], "checklist": [],
        },
    }]


def test_report_from_assessment_constructs_requested_subclass_at_id_length_boundary():
    class NewReport(model.Report):
        pass

    report = NewReport.from_assessment({"channel": "chat", "message": "text"}, {
        "assessment_id": "x" * 100, "score": 0, "priority": "LOW",
        "reasons": [], "checklist": [],
    })
    assert type(report) is NewReport
    assert report.assessment_id == "x" * 100


def test_report_from_assessment_leaves_missing_record_key_as_programming_error():
    with pytest.raises(KeyError, match="channel"):
        model.Report.from_assessment({}, {"assessment_id": "id"})


@pytest.fixture
def exposure_factory_inputs():
    return (
        {"channel": " chat ", "message": " Original\n ", "sender": " Sender ",
         "has_link": True, "link": " https://example.test ",
         "has_file": True, "file_name": " invoice.pdf ", "extra": object()},
        {"score": 60, "priority": "MEDIUM", "reasons": [" Original reason "],
         "checklist": [], "matched_rule": "Winner", "trace": [
             {"rule_name": "Skip", "matched": False, "score": None},
             {"rule_name": "Winner", "matched": True, "score": 60},
         ]},
        {"clicked": None, "downloaded": None, "submitted_category": None,
         "disclosure_answered": False},
    )


@pytest.mark.parametrize("answers", [
    (None, None, None, False), (False, False, None, True),
    (None, False, None, False), (True, None, None, False),
    (False, True, "password", True), (None, None, "otp", True),
])
@pytest.mark.parametrize("storage_type", [JsonReportStorage, SqliteReportStorage])
def test_report_from_exposure_preserves_explicit_answers_and_owned_storage_payload(
    exposure_factory_inputs, answers, storage_type, tmp_path,
):
    record, result, exposure = exposure_factory_inputs
    exposure.update(zip(exposure, answers))
    exposure["extra"] = object()
    before_record = dict(record)
    before_result = deepcopy(result)
    before_exposure = dict(exposure)
    expected = {
        "schema_version": 3, "assessment_id": " Existing ID ",
        "channel": " chat ", "message": " Original\n ", "sender": " Sender ",
        "has_link": True, "link": " https://example.test ",
        "has_file": True, "file_name": " invoice.pdf ",
        "result": {"score": 60, "priority": "MEDIUM", "reasons": [" Original reason "],
                   "checklist": [], "matched_rule": "Winner", "trace": [
                       {"rule_name": "Skip", "matched": False, "score": None},
                       {"rule_name": "Winner", "matched": True, "score": 60},
                   ]},
        "exposure": {"clicked": answers[0], "downloaded": answers[1],
                     "submitted_category": answers[2], "disclosure_answered": answers[3]},
    }

    report = model.Report.from_exposure(record, result, exposure, " Existing ID ")

    assert record == before_record and result == before_result and exposure == before_exposure
    assert report.to_dict() == expected
    assert report.exposure == model.ExposureAnswers(*answers)
    assert report.assessment_id == " Existing ID "
    record["message"] = "changed"
    result["reasons"].clear()
    result["trace"][-1]["rule_name"] = "changed"
    exposure["clicked"] = False
    output = report.to_dict()
    output["result"]["trace"][-1]["score"] = 0
    output["result"]["checklist"].append("changed")
    output["exposure"]["disclosure_answered"] = False
    assert report.to_dict() == expected
    serialized = json.loads(json.dumps(report.to_dict(), allow_nan=False))
    assert _validate_new(serialized) is serialized
    storage = storage_type(tmp_path / "history")
    storage.write_records([serialized])
    assert storage.read_records() == [expected]
    assert model.Report.from_legacy(storage.read_records()[0]).to_dict() == expected


@pytest.mark.parametrize("section,updates,error", [
    ("record", {"channel": " "}, "Invalid report text: channel"),
    ("record", {"message": None}, "Invalid report text: message"),
    ("record", {"sender": 1}, "Invalid report sender."),
    ("record", {"link": " "}, "Invalid report metadata: link"),
    ("record", {"file_name": False}, "Invalid report metadata: file_name"),
    ("record", {"has_link": 1}, "Invalid report metadata flag: has_link"),
    ("record", {"has_file": None}, "Invalid report metadata flag: has_file"),
    ("record", {"link": None}, "Report link and flag must agree."),
    ("record", {"has_file": False}, "A report filename requires a file clue."),
    ("exposure", {"clicked": 1}, "Invalid exposure action: clicked"),
    ("exposure", {"downloaded": "no"}, "Invalid exposure action: downloaded"),
    ("exposure", {"disclosure_answered": None}, "Invalid disclosure answer flag."),
    ("exposure", {"submitted_category": "email"}, "Invalid submitted category."),
    ("exposure", {"submitted_category": "password"},
     "Unanswered disclosure must have no submitted category."),
    ("result", {"score": True}, "Invalid stored score."),
    ("result", {"reasons": [" "]}, "Invalid stored text lists."),
    ("result", {"assessment_id": "nested"}, "Invalid stored assessment."),
    ("result", {"extra": False}, "Invalid stored assessment."),
    ("result", {"trace": []}, "Invalid stored rule trace."),
    ("result", {"matched_rule": "Other"}, "Stored rule trace does not match its assessment."),
])
def test_report_from_exposure_rejects_invalid_payload_before_constructor(
    exposure_factory_inputs, section, updates, error, monkeypatch,
):
    record, result, exposure = exposure_factory_inputs
    # Remove the deliberately ignored non-JSON extra for independent snapshot comparison.
    record.pop("extra")
    {"record": record, "result": result, "exposure": exposure}[section].update(updates)
    before = deepcopy((record, result, exposure))

    def forbidden(*args):
        pytest.fail("Invalid exposure reached the tolerant constructor")

    monkeypatch.setattr(model.Report, "__post_init__", forbidden)
    with pytest.raises(ValueError) as caught:
        model.Report.from_exposure(record, result, exposure, "id")
    assert str(caught.value) == error
    assert (record, result, exposure) == before


@pytest.mark.parametrize("identifier", [None, True, "", " \t ", "x" * 101])
def test_report_from_exposure_rejects_invalid_explicit_id(
    exposure_factory_inputs, identifier, monkeypatch,
):
    def forbidden(*args):
        pytest.fail("Invalid ID reached the tolerant constructor")

    monkeypatch.setattr(model.Report, "__post_init__", forbidden)
    with pytest.raises(ValueError, match="Invalid assessment identifier"):
        model.Report.from_exposure(*exposure_factory_inputs, identifier)


def test_report_from_exposure_propagates_canonical_exception_identity(
    exposure_factory_inputs, monkeypatch,
):
    error = ValueError("Canonical rejection")

    def reject(payload):
        assert len(payload) == 11 and payload["assessment_id"] == "id"
        raise error

    def forbidden(*args):
        pytest.fail("Factory used stored validation or constructed a rejected payload")

    monkeypatch.setattr(model, "_validate_new", reject)
    monkeypatch.setattr(model, "_validate_stored", forbidden)
    monkeypatch.setattr(model.Report, "__post_init__", forbidden)
    with pytest.raises(ValueError) as caught:
        model.Report.from_exposure(*exposure_factory_inputs, "id")
    assert caught.value is error


@pytest.mark.parametrize("section,key", [
    *[(0, key) for key in ("channel", "message", "sender", "has_link", "link",
                           "has_file", "file_name")],
    *[(2, key) for key in ("clicked", "downloaded", "submitted_category",
                           "disclosure_answered")],
])
def test_report_from_exposure_requires_source_keys(exposure_factory_inputs, section, key):
    del exposure_factory_inputs[section][key]
    with pytest.raises(KeyError) as caught:
        model.Report.from_exposure(*exposure_factory_inputs, "id")
    assert caught.value.args == (key,)


@pytest.mark.parametrize("argument_count", [0, 1, 2, 3])
def test_report_from_exposure_requires_all_arguments(exposure_factory_inputs, argument_count):
    args = (*exposure_factory_inputs, "id")
    with pytest.raises(TypeError):
        model.Report.from_exposure(*args[:argument_count])


def test_report_from_exposure_supports_nullable_clues_and_id_boundary(exposure_factory_inputs):
    class NewReport(model.Report):
        pass

    record, result, exposure = exposure_factory_inputs
    record.update(sender=None, has_link=False, link=None, has_file=False, file_name=None)
    result.pop("matched_rule")
    result.pop("trace")
    report = NewReport.from_exposure(record, result, exposure, "x" * 100)
    assert type(report) is NewReport
    assert report.assessment_id == "x" * 100
    assert report.sender is report.link is report.file_name is None
    assert report.has_link is report.has_file is False
    assert report.to_dict()["result"] == {
        "score": 60, "priority": "MEDIUM", "reasons": [" Original reason "], "checklist": [],
    }
