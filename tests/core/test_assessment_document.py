"""Tests for the neutral assessment document and its text representation."""

from phishreport.io.plain_text_renderer import PlainTextRenderer
from phishreport.io.render import AssessmentRenderer

RESULT = {
    "priority": "HIGH",
    "score": 80,
    "matched_rule": "SuspiciousInteractionRule",
    "trace": [
        {"rule_name": "DisclosureRule", "matched": False, "score": None},
        {"rule_name": "SuspiciousInteractionRule", "matched": True, "score": 80},
    ],
    "reasons": ["Urgency", "Credential request"],
    "checklist": ["Verify independently", "Do not reply"],
}


def test_assessment_document_preserves_order_and_trace_details():
    document = AssessmentRenderer().render(RESULT)

    assert document.available is True
    assert document.sections == (
        (
            "fields",
            "Assessment",
            (
                ("Priority", "HIGH"),
                ("Rule-based score", 80),
                ("Matched rule", "SuspiciousInteractionRule"),
            ),
        ),
        (
            "trace",
            "Rule evaluation trace",
            (
                ("DisclosureRule", (False, None)),
                ("SuspiciousInteractionRule", (True, 80)),
            ),
        ),
        ("bullets", "Reasons", (("Reason", "Urgency"), ("Reason", "Credential request"))),
        (
            "numbered",
            "Recommended actions",
            (("Action", "Verify independently"), ("Action", "Do not reply")),
        ),
    )


def test_assessment_document_omits_absent_trace():
    result = {key: value for key, value in RESULT.items() if key != "trace"}

    document = AssessmentRenderer().render(result)
    text = PlainTextRenderer().render(document)

    assert all(kind != "trace" for kind, _title, _entries in document.sections)
    assert "Rule evaluation trace" not in text


def test_assessment_document_marks_an_empty_result_unavailable():
    document = AssessmentRenderer().render({})

    assert document.available is False
    assert document.sections == ()
    assert PlainTextRenderer().render(document) == "No assessment available."
