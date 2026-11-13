"""Feedback value-object, service, and local persistence contracts."""

import json
from copy import deepcopy
from dataclasses import FrozenInstanceError

import pytest

from phishreport.feedback import FeedbackService, FeedbackStore


@pytest.fixture
def assessment_result():
    """Return fictional assessment context without storing the original message."""
    return {
        "assessment_id": "assessment-123",
        "score": 60,
        "priority": "MEDIUM",
        "reasons": ["The AI identified suspicious indicators."],
    }


def test_feedback_service_stores_correction_with_assessment_context(
    tmp_path, assessment_result
):
    store = FeedbackStore(tmp_path / "feedback.json")
    service = FeedbackService(store)
    original = deepcopy(assessment_result)

    feedback = service.submit(
        assessment_id="assessment-123",
        assessment_result=assessment_result,
        category="incorrect_priority",
        comment="This should be high priority.",
        corrected_priority="HIGH",
    )

    assert store.load() == [feedback]
    assert service.for_assessment("assessment-123") == [feedback]
    assert feedback.assessment_score == 60
    assert feedback.assessment_priority == "MEDIUM"
    assert feedback.assessment_reasons == ("The AI identified suspicious indicators.",)
    assert feedback.corrected_priority == "HIGH"
    assert feedback.category == "incorrect_priority"
    assert assessment_result == original
    saved = json.loads((tmp_path / "feedback.json").read_text(encoding="utf-8"))
    assert saved[0]["assessment_id"] == "assessment-123"
    assert "message" not in saved[0]


@pytest.mark.parametrize("category", ["application_bug", "usability_issue", "other"])
def test_feedback_store_accepts_product_feedback_categories(
    tmp_path, assessment_result, category
):
    service = FeedbackService(FeedbackStore(tmp_path / "feedback.json"))

    feedback = service.submit(
        assessment_id="assessment-123",
        assessment_result=assessment_result,
        category=category,
        comment="The assessment workflow needs review.",
    )

    assert feedback.category == category


def test_feedback_store_filters_submissions_by_assessment(tmp_path, assessment_result):
    service = FeedbackService(FeedbackStore(tmp_path / "feedback.json"))
    first = service.submit(
        assessment_id="assessment-123",
        assessment_result=assessment_result,
        category="false_positive",
    )
    second_result = {**assessment_result, "assessment_id": "assessment-456"}
    service.submit(
        assessment_id="assessment-456",
        assessment_result=second_result,
        category="false_negative",
    )

    assert service.for_assessment("assessment-123") == [first]
    assert service.for_assessment("assessment-missing") == []


def test_feedback_store_requires_corrected_priority_for_priority_corrections(
    tmp_path, assessment_result
):
    service = FeedbackService(FeedbackStore(tmp_path / "feedback.json"))

    with pytest.raises(ValueError, match="corrected priority"):
        service.submit(
            assessment_id="assessment-123",
            assessment_result=assessment_result,
            category="incorrect_priority",
        )

    assert not (tmp_path / "feedback.json").exists()


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "unknown"},
        {"assessment_id": " "},
        {"corrected_priority": "URGENT"},
        {"comment": "x" * 2001},
        {"assessment_id": "another-assessment"},
    ],
)
def test_feedback_service_rejects_invalid_feedback_without_writing(
    tmp_path, assessment_result, changes
):
    service = FeedbackService(FeedbackStore(tmp_path / "feedback.json"))
    arguments = {
        "assessment_id": "assessment-123",
        "assessment_result": assessment_result,
        "category": "other",
    }
    arguments.update(changes)

    with pytest.raises(ValueError):
        service.submit(**arguments)

    assert not (tmp_path / "feedback.json").exists()


@pytest.mark.parametrize(
    "assessment_result",
    [
        None,
        {"assessment_id": "assessment-123", "score": 101, "priority": "HIGH", "reasons": []},
        {
            "assessment_id": "assessment-123",
            "score": 40,
            "priority": "UNKNOWN",
            "reasons": [],
        },
        {
            "assessment_id": "assessment-123",
            "score": True,
            "priority": "LOW",
            "reasons": [],
        },
        {
            "assessment_id": "assessment-123",
            "score": 40,
            "priority": "LOW",
            "reasons": "not a list",
        },
    ],
)
def test_feedback_service_rejects_invalid_assessment_context(tmp_path, assessment_result):
    service = FeedbackService(FeedbackStore(tmp_path / "feedback.json"))

    with pytest.raises(ValueError):
        service.submit(
            assessment_id="assessment-123",
            assessment_result=assessment_result,
            category="other",
        )

    assert not (tmp_path / "feedback.json").exists()


def test_feedback_store_rejects_malformed_history_without_overwriting(
    tmp_path, assessment_result
):
    path = tmp_path / "feedback.json"
    contents = '[{"feedback_id":"duplicate","feedback_id":"shadow"}]'
    path.write_text(contents, encoding="utf-8")
    service = FeedbackService(FeedbackStore(path))

    with pytest.raises(ValueError):
        service.submit(
            assessment_id="assessment-123",
            assessment_result=assessment_result,
            category="other",
        )

    assert path.read_text(encoding="utf-8") == contents


def test_feedback_store_missing_file_is_empty(tmp_path):
    assert FeedbackStore(tmp_path / "missing.json").load() == []


def test_feedback_value_is_immutable(tmp_path, assessment_result):
    feedback = FeedbackService(FeedbackStore(tmp_path / "feedback.json")).submit(
        assessment_id="assessment-123",
        assessment_result=assessment_result,
        category="false_negative",
    )

    with pytest.raises(FrozenInstanceError):
        feedback.category = "other"
