"""The message and feedback factories build what the free functions built."""

from types import SimpleNamespace

from phishreport.bot.exposure import ExposureSession
from phishreport.bot.feedback_ui import FeedbackKeyboardFactory
from phishreport.bot.messages import MessageFactory


def rows(markup):
    return [[(b.text, b.callback_data) for b in row] for row in markup.inline_keyboard]


def test_message_factory_card_preview_and_keyboards():
    long_text = "x" * 401

    assert MessageFactory.confirmation_preview("short") == "short"
    assert MessageFactory.confirmation_preview(long_text) == "x" * 400 + "..."
    assert MessageFactory.build_confirmation_card("hi") == (
        'Check this message?\n\n"hi"\n\nThis text is sent to the AI provider for analysis.'
    )
    assert rows(MessageFactory.build_confirmation_keyboard("tok")) == [
        [("Yes, check it", "exposure:tok:confirm"), ("Cancel", "exposure:tok:cancel")]
    ]
    assert MessageFactory.build_status_keyboard(False) is None
    assert rows(MessageFactory.build_status_keyboard(True)) == [
        [("Download all reports (CSV)", "status:csv"), ("Download summary (TXT)", "status:summary")]
    ]


def test_message_factory_exposure_keyboard_follows_the_session():
    session = SimpleNamespace(
        saved=True, finished=False, token="tok", exposure={"clicked": None}
    )
    assert rows(MessageFactory.build_exposure_keyboard(session)) == [
        [("Clicked link", "exposure:tok:clicked"),
         ("Shared a password/OTP", "exposure:tok:password")],
        [("Nothing happened", "exposure:tok:nothing")],
    ]
    session.exposure = {"clicked": True}
    assert rows(MessageFactory.build_exposure_keyboard(session)) == [
        [("Shared a password/OTP", "exposure:tok:password"),
         ("Nothing else", "exposure:tok:nothing")]
    ]
    session.finished = True
    assert MessageFactory.build_exposure_keyboard(session) is None
    assert ExposureSession  # the factory accepts the real session type


def test_message_factory_summary_document_lists_sections():
    summary = SimpleNamespace(
        total=2,
        sections=[SimpleNamespace(title="By priority", rows=[("HIGH", 1), ("LOW", 1)])],
    )

    assert MessageFactory.build_summary_document(summary) == (
        "=== Report summary ===\nShowing: all reports\nReports: 2\n\n"
        "By priority:\n - HIGH: 1\n - LOW: 1\n"
    )
    assert MessageFactory.build_summary_document(SimpleNamespace(total=0, sections=[])) == (
        "=== Report summary ===\nShowing: all reports\nReports: 0\nNo saved reports match.\n"
    )


def test_feedback_factory_keyboards_keep_their_callback_data():
    assert rows(FeedbackKeyboardFactory.assessment_feedback_keyboard("a1")) == [
        [("Suggest a correction", "fb:o:a1")]
    ]
    categories = rows(FeedbackKeyboardFactory.feedback_category_keyboard("a1"))
    assert categories[0] == [("False positive", "fb:c:fp:a1"), ("False negative", "fb:c:fn:a1")]
    assert categories[-1] == [("Cancel", "fb:x:a1")]
    assert rows(FeedbackKeyboardFactory.corrected_priority_keyboard("a1")) == [
        [("HIGH", "fb:p:H:a1"), ("MEDIUM", "fb:p:M:a1"), ("LOW", "fb:p:L:a1")],
        [("Cancel", "fb:x:a1")],
    ]
    assert rows(FeedbackKeyboardFactory.feedback_comment_keyboard("a1")) == [
        [("Submit without comment", "fb:s:a1")],
        [("Cancel", "fb:x:a1")],
    ]
