"""Shared field expectations for the plain-text and HTML renderers."""

from phishreport.io.html_alert_renderer import HTMLAlertRenderer
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

SHARED_FIELD_EXPECTATIONS = [
    ("priority", ("Priority: High",), ("<b>HIGH risk</b>",)),
    ("score", ("Rule-based score: 80",), ("<b>Score:</b> 80/100",)),
    (
        "matched rule",
        ("Matched rule: SuspiciousInteractionRule",),
        ("Matched rule:</b> SuspiciousInteractionRule",),
    ),
    (
        "trace",
        ("Rule evaluation trace:", " - DisclosureRule: not matched"),
        ("<b>Rule evaluation trace</b>", "• DisclosureRule: not matched"),
    ),
    (
        "reasons",
        ("\nReasons:", " - Urgency"),
        ("<b>Why it was flagged</b>", "• Urgency"),
    ),
    (
        "checklist",
        ("\nRecommended actions:", "1. Verify independently"),
        ("<b>What to do</b>", "1. Verify independently"),
    ),
]


def test_text_and_html_renderers_cover_the_shared_assessment_fields():
    document = AssessmentRenderer().render(RESULT)
    text = PlainTextRenderer().render(document)
    html = HTMLAlertRenderer().render(document)

    for _field, text_fragments, html_fragments in SHARED_FIELD_EXPECTATIONS:
        assert all(fragment in text for fragment in text_fragments)
        assert all(fragment in html for fragment in html_fragments)


def test_both_renderers_omit_an_absent_trace_section():
    result = {key: value for key, value in RESULT.items() if key != "trace"}
    document = AssessmentRenderer().render(result)

    assert "Rule evaluation trace" not in PlainTextRenderer().render(document)
    assert "Rule evaluation trace" not in HTMLAlertRenderer().render(document)
