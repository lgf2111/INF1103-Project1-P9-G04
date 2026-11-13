"""Offline tests for feedback records and local persistence."""

import json

import pytest

from feedback_store import FeedbackStore


@pytest.fixture
def assessment_result():
    """Return a fictional assessment context without an email body."""
    return {
        "score": 60,
        "priority": "MEDIUM",
        "reasons": ["The message has suspicious indicators."],
        "matched_rule": "SuspiciousRule",
    }


def test_feedback_store_submits_and_reloads_context(tmp_path, assessment_result):
    store = FeedbackStore(tmp_path / "feedback.json")

    feedback = store.submit(
        assessment_id="assessment-123",
        assessment_result=assessment_result,
        category="incorrect_priority",
        comment="I think this should be high priority.",
        corrected_priority="HIGH",
    )

    saved = store.load()
    assert saved == [feedback]
    assert feedback.assessment_id == "assessment-123"
    assert feedback.assessment_score == 60
    assert feedback.assessment_priority == "MEDIUM"
    assert feedback.assessment_reasons == ("The message has suspicious indicators.",)
    assert feedback.matched_rule == "SuspiciousRule"
    assert feedback.corrected_priority == "HIGH"
    assert (tmp_path / "feedback.json").exists()


def test_feedback_store_filters_by_assessment(tmp_path, assessment_result):
    store = FeedbackStore(tmp_path / "feedback.json")
    first = store.submit(
        assessment_id="assessment-123",
        assessment_result=assessment_result,
        category="false_positive",
    )
    store.submit(
        assessment_id="assessment-456",
        assessment_result=assessment_result,
        category="other",
    )

    assert store.for_assessment("assessment-123") == [first]
    assert store.for_assessment("assessment-missing") == []


def test_feedback_store_leaves_report_data_and_assessment_result_unchanged(
    tmp_path, assessment_result
):
    original = json.loads(json.dumps(assessment_result))
    store = FeedbackStore(tmp_path / "feedback.json")

    store.submit(
        assessment_id="assessment-123",
        assessment_result=assessment_result,
        category="false_negative",
        comment="This looks like a phishing attempt.",
    )

    assert assessment_result == original
    saved = json.loads((tmp_path / "feedback.json").read_text(encoding="utf-8"))
    assert "message" not in saved[0]
    assert saved[0]["assessment_id"] == "assessment-123"


@pytest.mark.parametrize(
    "changes",
    [
        {"category": "unknown"},
        {"assessment_id": " "},
        {"corrected_priority": "URGENT"},
        {"comment": "x" * 2001},
    ],
)
def test_feedback_store_rejects_invalid_feedback_without_writing(
    tmp_path, assessment_result, changes
):
    store = FeedbackStore(tmp_path / "feedback.json")
    arguments = {
        "assessment_id": "assessment-123",
        "assessment_result": assessment_result,
        "category": "other",
    }
    arguments.update(changes)

    with pytest.raises(ValueError):
        store.submit(**arguments)

    assert not (tmp_path / "feedback.json").exists()


@pytest.mark.parametrize(
    "assessment_result",
    [
        None,
        {"score": 101, "priority": "HIGH", "reasons": []},
        {"score": 40, "priority": "UNKNOWN", "reasons": []},
        {"score": 40, "priority": "LOW", "reasons": "not a list"},
        {"score": True, "priority": "LOW", "reasons": []},
    ],
)
def test_feedback_store_rejects_invalid_assessment_context(tmp_path, assessment_result):
    store = FeedbackStore(tmp_path / "feedback.json")

    with pytest.raises(ValueError):
        store.submit(
            assessment_id="assessment-123",
            assessment_result=assessment_result,
            category="other",
        )

    assert not (tmp_path / "feedback.json").exists()


@pytest.mark.parametrize(
    "contents",
    [
        "{broken",
        '[{"feedback_id":"a","feedback_id":"b"}]',
        '[{"feedback_id":"a","assessment_id":"assessment-123"}]',
        "NaN",
    ],
)
def test_feedback_store_rejects_malformed_history_without_overwriting(
    tmp_path, assessment_result, contents
):
    path = tmp_path / "feedback.json"
    path.write_text(contents, encoding="utf-8")
    store = FeedbackStore(path)

    with pytest.raises(ValueError):
        store.submit(
            assessment_id="assessment-123",
            assessment_result=assessment_result,
            category="other",
        )

    assert path.read_text(encoding="utf-8") == contents


def test_feedback_store_missing_file_is_empty(tmp_path):
    assert FeedbackStore(tmp_path / "feedback.json").load() == []


def test_feedback_store_requires_assessment_id_for_query(tmp_path):
    store = FeedbackStore(tmp_path / "feedback.json")

    with pytest.raises(ValueError, match="Assessment identifier"):
        store.for_assessment(" ")
