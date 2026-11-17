"""Preserve canonical model behavior through the shared rendering pipeline."""

from copy import deepcopy

import pytest

from phishreport.assessment import AssessmentSnapshot
from phishreport.bot.exposure import ExposureSession
from phishreport.bot.messages import PhishingAlertFormatter, ResultFormatter
from phishreport.io.plain_text_renderer import PlainTextRenderer
from phishreport.io.presenter import ReportPresenter
from phishreport.io.render import AssessmentRenderer
from phishreport.model import SCHEMA_VERSION, SCHEMA_VERSION_KEY, Report

RESULT = {
    "score": 80,
    "priority": "HIGH",
    "reasons": ["Suspicious link"],
    "checklist": ["Verify independently"],
}


def test_shared_renderer_accepts_the_same_typed_result_as_saved_report_presenter():
    source = {SCHEMA_VERSION_KEY: SCHEMA_VERSION, "assessment_id": "saved-assessment",
              "channel": "sms", "message": "Fictional message", "result": deepcopy(RESULT)}
    report = Report(source)
    renderer = AssessmentRenderer()
    expected = renderer.render(RESULT)
    assert renderer.render(report.result) == expected

    class Terminal:
        def __init__(self):
            self.lines = []

        def write(self, *parts):
            self.lines.append(" ".join(str(part) for part in parts))

    terminal = Terminal()
    ReportPresenter(terminal).display_record(source)
    text = "\n".join(terminal.lines)
    assert "Rule-based score: 80" in text
    assert "Suspicious link" in text
    assert source["result"] == RESULT


@pytest.mark.parametrize("result", [None, {}])
def test_absent_results_stay_unavailable(result):
    document = AssessmentRenderer().render(result)
    assert document.available is False
    assert PlainTextRenderer().render(document) == "No assessment available."


def test_shared_renderer_preserves_tolerant_historical_model_projection():
    result = {
        "score": True,
        "priority": 12,
        "reasons": ["Retained reason", 7],
        "checklist": [None, "Retained action"],
        "trace": [{"rule_name": "broken", "matched": "false"}],
    }
    before = deepcopy(result)
    renderer = AssessmentRenderer()
    document = renderer.render(result)
    assert document == renderer.render(Report({"result": result}).result)
    text = PlainTextRenderer().render(document)
    assert "Rule-based score: Unavailable" in text
    assert "Retained reason" in text
    assert "Retained action" in text
    assert "broken" not in text
    assert result == before


def test_saved_telegram_card_is_the_compact_committed_result():
    session = ExposureSession({}, AssessmentSnapshot({}, deepcopy(RESULT)),
                              chat_id=1, user_id=2, message_id=3)
    session.report = {
        SCHEMA_VERSION_KEY: SCHEMA_VERSION,
        "result": deepcopy(RESULT),
        "exposure": {"clicked": True, "downloaded": False,
                     "submitted_category": "password", "disclosure_answered": True},
    }
    session.saved = True
    before = deepcopy(session.report)

    text = ResultFormatter().format(session.result, session=session)

    assert "Priority: High" in text
    assert "Rule-based score: 80" in text
    assert "Suspicious link" in text
    assert "Rule evaluation trace" not in text
    assert "Clicked link: Yes" not in text
    assert "Downloaded file: No" not in text
    assert "Information submitted: Password" not in text
    assert "Exposure unconfirmed" not in text
    assert ResultFormatter.FOOTER not in text
    assert session.report == before


def test_typed_alert_values_are_escaped_at_the_html_boundary():
    result = {**RESULT, "reasons": ["<script>unsafe</script>"],
              "checklist": ["<b>independent check</b>"]}
    text = PhishingAlertFormatter().format(
        Report({"result": result}).result, '<sender&>', subject='<subject>',
        source_url='https://example.test/?a="quoted"&b=1',
    )
    assert "<script>" not in text
    assert "&lt;script&gt;unsafe&lt;/script&gt;" in text
    assert "&lt;sender&amp;&gt;" in text
    assert "&lt;subject&gt;" in text
    assert "&quot;quoted&quot;&amp;b=1" in text


def test_large_unicode_telegram_output_retains_footer_within_utf16_limit():
    result = {**RESULT, "reasons": ["\U0001f6a8" * 5000]}
    text = ResultFormatter().format(result)
    assert len(text.encode("utf-16-le")) // 2 <= 4000
    assert text.endswith(ResultFormatter.FOOTER)
