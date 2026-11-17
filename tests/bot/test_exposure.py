"""Saved exposure session state is isolated without bot, AI or storage I/O."""

import asyncio
import importlib
import re
from copy import deepcopy
from unittest.mock import Mock

import pytest

from phishreport.assessment import AssessmentService, AssessmentSnapshot
from phishreport.bot.messages import ChatRecordBuilder
from phishreport.data.validator import ReportValidator
from phishreport.logic import LogicManager

ALLOWED_CHAT_ID = 12345
FINDINGS = {"suspicious": True, "credential_request": True, "insufficient_context": False}


@pytest.fixture
def exposure_module():
    return importlib.import_module("phishreport.bot.exposure")


@pytest.fixture
def inputs():
    record = {
        "channel": "chat",
        "message": "Verify your password now.",
        "clicked": False,
        "downloaded": False,
        "submitted_category": None,
        "metadata": {"labels": ["original"]},
    }
    snapshot = AssessmentSnapshot(
        findings={"suspicious": True, "details": {"labels": ["original"]}},
        result={"score": 60, "reasons": [{"labels": ["original"]}]},
    )
    return record, snapshot


@pytest.fixture
def pending(exposure_module):
    record = ChatRecordBuilder().build(
        "Verify your password at https://example.test. See invoice.pdf.", sender="Sender"
    )
    record["metadata"] = {"labels": ["original"]}
    ai = Mock()
    ai.assess.return_value = {
        **FINDINGS, "details": {"labels": ["original"]},
    }
    service = AssessmentService(ai, LogicManager())
    snapshot = service.assess_with_findings(record)
    session = exposure_module.ExposureSession(
        record, snapshot, chat_id=101, user_id=202, message_id=303
    )
    return session, service, ai, record, snapshot


def test_new_session_is_owned_saved_once_and_accepts_answers_later(pending):
    session, _, _, _, _ = pending

    assert (session.chat_id, session.user_id, session.message_id) == (101, 202, 303)
    assert session.reply_message_id is None
    assert session.assessment_id and len(session.assessment_id) <= 100
    assert session.exposure == {
        "clicked": None,
        "downloaded": None,
        "submitted_category": None,
        "disclosure_answered": False,
    }
    assert session.answered is False
    assert session.saved is False
    assert session.dismissed is False
    assert session.report is None
    assert isinstance(session.lock, asyncio.Lock)
    assert not session.lock.locked()


@pytest.mark.parametrize("direction", ["caller-to-session", "session-to-caller"])
def test_session_deep_copies_record_findings_and_result(exposure_module, inputs, direction):
    record, snapshot = inputs
    session = exposure_module.ExposureSession(
        record, snapshot, chat_id=101, user_id=202, message_id=303
    )
    assert session.record == record
    assert session.findings == snapshot.findings
    assert session.result == snapshot.result
    before = deepcopy((record, snapshot))

    if direction == "caller-to-session":
        record["metadata"]["labels"].append("changed")
        snapshot.findings["details"]["labels"].append("changed")
        snapshot.result["reasons"][0]["labels"].append("changed")
        assert (session.record, session.findings, session.result) == (
            before[0], before[1].findings, before[1].result
        )
    else:
        session.record["metadata"]["labels"].append("changed")
        session.findings["details"]["labels"].append("changed")
        session.result["reasons"][0]["labels"].append("changed")
        assert (record, snapshot) == before


@pytest.mark.parametrize("prior_answer", [False, True])
def test_session_starts_with_unknown_answers_despite_record_flags(
    exposure_module, inputs, prior_answer,
):
    record, snapshot = inputs
    record.update(
        clicked=prior_answer,
        downloaded=prior_answer,
        submitted_category="password" if prior_answer else None,
        disclosure_answered=True,
        exposure={"clicked": prior_answer, "disclosure_answered": True},
    )

    session = exposure_module.ExposureSession(
        record, snapshot, chat_id=101, user_id=202, message_id=303
    )

    assert session.exposure == {
        "clicked": None,
        "downloaded": None,
        "submitted_category": None,
        "disclosure_answered": False,
    }
    assert session.record == record


@pytest.mark.parametrize(
    ("action", "exposure", "score", "priority"),
    [
        ("clicked", {"clicked": True, "downloaded": None,
                     "submitted_category": None, "disclosure_answered": False},
         80, "HIGH"),
        ("password", {"clicked": None, "downloaded": None,
                      "submitted_category": "password", "disclosure_answered": True},
         90, "HIGH"),
    ],
)
def test_answer_projects_one_answer_and_rescores_without_changing_the_session(
    pending, action, exposure, score, priority,
):
    session, service, ai, _, _ = pending
    before = deepcopy((session.record, session.findings, session.result, session.exposure))
    identities = (session.record, session.findings, session.result, session.lock)

    candidate, result = session.answer(action, service)

    assert candidate == exposure
    assert (result["score"], result["priority"]) == (score, priority)
    assert (session.record, session.findings, session.result, session.exposure) == before
    assert all(a is b for a, b in zip(
        identities, (session.record, session.findings, session.result, session.lock),
        strict=True,
    ))
    assert (session.saved, session.dismissed, session.report) == (False, False, None)
    ai.assess.assert_called_once()


def test_answer_keeps_unknown_groups_and_composes_with_an_existing_answer(pending):
    session, service, ai, _, _ = pending
    clicked, result = session.answer("clicked", service)
    session.commit(clicked, result, session.build_report(service, exposure=clicked, result=result))
    assert session.answered is True

    candidate, result = session.answer("password", service)

    assert candidate == {
        "clicked": True, "downloaded": None,
        "submitted_category": "password", "disclosure_answered": True,
    }
    assert result["score"] == 90
    ai.assess.assert_called_once()


def test_repeating_a_recorded_answer_reports_no_change(pending):
    session, service, ai, _, _ = pending
    exposure, result = session.answer("clicked", service)
    session.commit(
        exposure, result, session.build_report(service, exposure=exposure, result=result),
    )
    service.rescore = Mock(wraps=service.rescore)

    assert session.answer("clicked", service) is None

    service.rescore.assert_not_called()
    ai.assess.assert_called_once()


@pytest.mark.parametrize("action", ["", "Clicked", " clicked", "finish", None, True, 1, [], {}])
def test_answer_rejects_unknown_actions_before_collaborators(pending, action):
    session, _, _, _, _ = pending
    assessment = Mock()
    before = deepcopy(session.__dict__, {id(session.lock): session.lock})

    with pytest.raises(ValueError):
        session.answer(action, assessment)

    assert session.__dict__ == before
    assessment.rescore.assert_not_called()


def test_answer_rejects_dismissed_and_expired_sessions(pending, exposure_module, monkeypatch):
    session, service, _, record, snapshot = pending
    session.dismiss()
    before = deepcopy(session.__dict__, {id(session.lock): session.lock})
    with pytest.raises(ValueError, match="dismissed"):
        session.answer("clicked", service)
    assert session.__dict__ == before

    fresh = exposure_module.ExposureSession(
        deepcopy(record),
        AssessmentSnapshot(deepcopy(snapshot.findings), deepcopy(snapshot.result)),
        chat_id=101, user_id=202, message_id=303,
    )
    monkeypatch.setattr(exposure_module.time, "monotonic", lambda: fresh.expires_at)
    with pytest.raises(ValueError, match="expired"):
        fresh.answer("clicked", service)


def test_answer_accepts_immediately_before_expiry(pending, exposure_module, monkeypatch):
    session, service, _, _, _ = pending
    monkeypatch.setattr(exposure_module.time, "monotonic", lambda: session.expires_at - 0.001)

    _, result = session.answer("clicked", service)

    assert result["score"] == 80


@pytest.mark.parametrize("action", ["password", "clicked"])
def test_answer_failure_leaves_every_value_and_identity_intact(pending, action):
    session, _, _, record, snapshot = pending
    before = deepcopy((session.__dict__, record, snapshot), {id(session.lock): session.lock})
    identities = dict(session.__dict__)
    error = RuntimeError("re-score failed")

    def rescore(working_record, working_findings):
        working_record["metadata"]["labels"].clear()
        working_findings["details"]["labels"].clear()
        raise error

    assessment = Mock()
    assessment.rescore.side_effect = rescore
    with pytest.raises(RuntimeError) as raised:
        session.answer(action, assessment)

    assert raised.value is error
    assert (session.__dict__, record, snapshot) == before
    assert all(session.__dict__[key] is value for key, value in identities.items())


def test_answer_isolates_collaborator_inputs_and_outputs(pending):
    session, _, _, record, snapshot = pending
    before = deepcopy((session.record, session.findings, record, snapshot))
    retained = {}

    def rescore(working_record, working_findings):
        retained.update(record=working_record, findings=working_findings)
        return {"score": 80, "priority": "HIGH", "reasons": ["test"], "checklist": ["act"]}

    assessment = Mock()
    assessment.rescore.side_effect = rescore
    candidate, result = session.answer("clicked", assessment)
    candidate["clicked"] = False
    result["reasons"].append("caller")

    assert retained["record"]["metadata"]["labels"] == ["original"]
    assert retained["findings"]["details"]["labels"] == ["original"]
    assert (session.record, session.findings, record, snapshot) == before
    assert session.exposure["clicked"] is None
    assessment.assess.assert_not_called()


def test_build_report_is_a_valid_v3_revision_with_one_identifier(pending):
    session, service, ai, _, _ = pending

    initial = session.build_report(service)
    candidate, result = session.answer("clicked", service)
    revised = session.build_report(service, exposure=candidate, result=result)

    assert ReportValidator().validate_new(initial) == initial
    assert ReportValidator().validate_new(revised) == revised
    assert initial["schema_version"] == 3
    assert initial["assessment_id"] == revised["assessment_id"] == session.assessment_id
    assert initial["message"] == session.record["message"]
    assert initial["sender"] == "Sender"
    assert (initial["has_link"], initial["link"]) == (True, "https://example.test")
    assert (initial["has_file"], initial["file_name"]) == (True, "invoice.pdf")
    assert initial["result"]["score"] == 60
    assert revised["result"]["score"] == 80
    assert initial["exposure"] == {
        "clicked": None, "downloaded": None,
        "submitted_category": None, "disclosure_answered": False,
    }
    assert revised["exposure"]["clicked"] is True
    assert session.exposure["clicked"] is None
    ai.assess.assert_called_once()


def test_build_report_copies_inputs_and_output(pending):
    session, service, _, record, snapshot = pending
    candidate = {
        "clicked": True, "downloaded": None,
        "submitted_category": None, "disclosure_answered": False,
    }
    before = deepcopy((session.__dict__, record, snapshot), {id(session.lock): session.lock})
    identities = dict(session.__dict__)

    report = session.build_report(service, exposure=candidate)
    first = deepcopy(report)
    candidate["clicked"] = False
    report["result"]["reasons"].append("caller")
    report["exposure"]["clicked"] = False

    assert (session.__dict__, record, snapshot) == before
    assert all(session.__dict__[key] is value for key, value in identities.items())
    assert session.build_report(
        service, exposure={"clicked": True, "downloaded": None,
                           "submitted_category": None, "disclosure_answered": False},
    ) == first
    assert first["exposure"]["clicked"] is True


def test_commit_adopts_one_revision_and_dismiss_keeps_it(pending):
    session, service, _, _, _ = pending
    candidate, result = session.answer("password", service)
    report = session.build_report(service, exposure=candidate, result=result)

    session.commit(candidate, result, report)

    assert session.saved is True
    assert session.exposure == candidate
    assert session.result == result
    assert session.report == report
    assert session.report is not report
    assert session.dismissed is False
    assert session.answered is True

    stored = deepcopy(session.report)
    session.dismiss()

    assert session.dismissed is True
    assert session.report == stored
    assert session.result["score"] == 90


def test_sessions_keep_payloads_and_lifecycle_independent(exposure_module, inputs):
    first = exposure_module.ExposureSession(*inputs, chat_id=101, user_id=202, message_id=303)
    second = exposure_module.ExposureSession(*inputs, chat_id=101, user_id=202, message_id=304)
    second_before = deepcopy((second.record, second.findings, second.result, second.exposure))

    first.record["metadata"]["labels"].append("changed")
    first.findings["details"]["labels"].append("changed")
    first.result["reasons"][0]["labels"].append("changed")
    first.dismiss()

    assert (second.record, second.findings, second.result, second.exposure) == second_before
    assert first.lock is not second.lock
    assert not second.lock.locked()
    assert second.dismissed is False
    assert first.assessment_id != second.assessment_id


def test_session_lifetime_is_thirty_minutes_from_monotonic_creation(
    exposure_module, inputs, monkeypatch,
):
    ticks = iter([1234.5, 1276.25])
    monkeypatch.setattr(exposure_module.time, "monotonic", lambda: next(ticks))

    first = exposure_module.ExposureSession(*inputs, chat_id=101, user_id=202, message_id=303)
    second = exposure_module.ExposureSession(*inputs, chat_id=101, user_id=202, message_id=304)

    assert first.created_at == 1234.5
    assert first.expires_at == 3034.5
    assert second.created_at == 1276.25
    assert second.expires_at == 3076.25


def test_session_token_is_urlsafe_and_fits_callback_payload(exposure_module, inputs):
    session = exposure_module.ExposureSession(*inputs, chat_id=101, user_id=202, message_id=303)

    assert re.fullmatch(r"[A-Za-z0-9_-]{16}", session.token)
    assert len(f"exposure:{session.token}:password".encode("utf-8")) < 64


@pytest.fixture
def pending_record():
    return {
        "channel": "chat",
        "message": "Verify your password now.",
        "sender": None,
        "metadata": {"labels": ["original"]},
    }


def test_pending_confirmation_waits_with_owned_source_and_raw_record(
    exposure_module, pending_record,
):
    pending = exposure_module.PendingConfirmation(
        pending_record, chat_id=101, user_id=202, message_id=303,
    )

    assert (pending.chat_id, pending.user_id, pending.message_id) == (101, 202, 303)
    assert pending.record == pending_record
    assert pending.card_message_id is None
    assert pending.resolution is None
    assert isinstance(pending.lock, asyncio.Lock) and not pending.lock.locked()
    assert (
        pending.created_at
        == pending.expires_at - exposure_module.CONFIRMATION_TIMEOUT_SECONDS
    )
    assert not pending.expired


@pytest.mark.parametrize("direction", ["caller-to-pending", "pending-to-caller"])
def test_pending_confirmation_deep_copies_the_record(
    exposure_module, pending_record, direction,
):
    pending = exposure_module.PendingConfirmation(
        pending_record, chat_id=101, user_id=202, message_id=303,
    )

    if direction == "caller-to-pending":
        pending_record["metadata"]["labels"].append("changed")
        assert pending.record["metadata"]["labels"] == ["original"]
    else:
        pending.record["metadata"]["labels"].append("changed")
        assert pending_record["metadata"]["labels"] == ["original"]


def test_pending_confirmation_expires_after_its_own_window(
    exposure_module, pending_record, monkeypatch,
):
    window = exposure_module.CONFIRMATION_TIMEOUT_SECONDS
    ticks = iter([100.0, 100.0 + window - 0.001, 100.0 + window])
    monkeypatch.setattr(exposure_module.time, "monotonic", lambda: next(ticks))

    pending = exposure_module.PendingConfirmation(
        pending_record, chat_id=101, user_id=202, message_id=303,
    )

    assert pending.created_at == 100.0
    assert pending.expires_at == 100.0 + window
    assert not pending.expired
    assert pending.expired


def test_confirmation_and_exposure_sessions_have_separate_windows(
    exposure_module, pending_record, inputs, monkeypatch,
):
    now = 1000.0
    monkeypatch.setattr(exposure_module.time, "monotonic", lambda: now)

    confirmation = exposure_module.PendingConfirmation(
        pending_record, chat_id=101, user_id=202, message_id=303,
    )
    session = exposure_module.ExposureSession(
        *inputs, chat_id=101, user_id=202, message_id=303,
    )

    assert (
        confirmation.expires_at - now
        == exposure_module.CONFIRMATION_TIMEOUT_SECONDS
    )
    assert session.expires_at - now == exposure_module.SESSION_TIMEOUT_SECONDS
    assert (
        exposure_module.CONFIRMATION_TIMEOUT_SECONDS
        < exposure_module.SESSION_TIMEOUT_SECONDS
    )


def test_pending_confirmation_token_is_urlsafe_and_fits_callback_payload(
    exposure_module, pending_record,
):
    pending = exposure_module.PendingConfirmation(
        pending_record, chat_id=101, user_id=202, message_id=303,
    )

    assert re.fullmatch(r"[A-Za-z0-9_-]{16}", pending.token)
    assert len(f"exposure:{pending.token}:confirm".encode("utf-8")) < 64


def test_confirmation_actions_are_disjoint_from_follow_up_answers(exposure_module):
    assert exposure_module.CONFIRM_ACTIONS == {"confirm", "cancel"}
    assert exposure_module.CONFIRM_ACTIONS.isdisjoint(exposure_module.ANSWER_ACTIONS)
