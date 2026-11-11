"""Pending exposure session state is isolated without bot or AI I/O."""

import asyncio
import importlib
import re
from copy import deepcopy
from unittest.mock import Mock

import pytest

from phishreport.assessment import AssessmentService, AssessmentSnapshot
from phishreport.bot.messages import ChatRecordBuilder
from phishreport.logic import LogicManager


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
        "suspicious": True, "credential_request": True, "insufficient_context": False,
        "details": {"labels": ["original"]},
    }
    service = AssessmentService(ai, LogicManager())
    snapshot = service.assess_with_findings(record)
    session = exposure_module.ExposureSession(
        record, snapshot, chat_id=101, user_id=202, message_id=303
    )
    return session, service, ai, record, snapshot


@pytest.mark.parametrize(
    ("action", "clicked", "downloaded", "category", "answered", "score", "priority"),
    [
        ("clicked", True, False, None, False, 80, "HIGH"),
        ("downloaded", False, True, None, False, 80, "HIGH"),
        ("both", True, True, None, False, 80, "HIGH"),
        ("neither", False, False, None, False, 60, "MEDIUM"),
        ("password", None, None, "password", True, 90, "HIGH"),
        ("otp", None, None, "otp", True, 90, "HIGH"),
        ("no_disclosure", None, None, None, True, 60, "MEDIUM"),
    ],
)
def test_apply_answer_projects_confirmed_answers_and_scores_without_io(
    pending, action, clicked, downloaded, category, answered, score, priority
):
    session, service, ai, record, snapshot = pending
    before = deepcopy((session.record, session.findings, record, snapshot))
    identities = (session.record, session.findings, session.lock)
    # No storage or Telegram collaborator is supplied: answering only re-scores.
    result = session.apply_answer(action, service)

    assert session.exposure == {
        "clicked": clicked, "downloaded": downloaded,
        "submitted_category": category, "disclosure_answered": answered,
    }
    assert (result["score"], result["priority"]) == (score, priority)
    assert result == session.result
    assert (session.record, session.findings, record, snapshot) == before
    assert all(a is b for a, b in zip(
        identities, (session.record, session.findings, session.lock), strict=True
    ))
    assert (session.completed, session.saved, session.report) == (False, False, None)
    ai.assess.assert_called_once()


def test_apply_answer_preserves_other_group_and_reverts_without_another_ai_call(pending):
    session, service, ai, _, _ = pending
    for action, answers, score in [
        ("password", (None, None, "password", True), 90),
        ("both", (True, True, "password", True), 90),
        ("downloaded", (False, True, "password", True), 90),
        ("otp", (False, True, "otp", True), 90),
        ("no_disclosure", (False, True, None, True), 80),
        ("clicked", (True, False, None, True), 80),
        ("neither", (False, False, None, True), 60),
        ("neither", (False, False, None, True), 60),
    ]:
        assert session.apply_answer(action, service)["score"] == score
        assert tuple(session.exposure.values()) == answers
        assert not session.saved
    ai.assess.assert_called_once()


@pytest.mark.parametrize("action", ["", "Clicked", " clicked", "finish", None, True, 1, [], {}])
def test_apply_answer_rejects_invalid_actions_before_collaborators(pending, action):
    session, _, _, _, _ = pending
    assessment = Mock()
    before = deepcopy(session.__dict__, {id(session.lock): session.lock})

    with pytest.raises(ValueError):
        session.apply_answer(action, assessment)

    assert session.__dict__ == before
    assessment.assert_not_called()
    assessment.rescore.assert_not_called()
    assessment.assess.assert_not_called()


@pytest.mark.parametrize("state", ["completed", "saved", "boundary", "expired"])
def test_apply_answer_rejects_closed_or_expired_sessions(
    pending, exposure_module, monkeypatch, state
):
    session, _, _, _, _ = pending
    if state in ("completed", "saved"):
        setattr(session, state, True)
    tick = session.expires_at + (1 if state == "expired" else 0)
    if state in ("completed", "saved"):
        tick = session.created_at
    monkeypatch.setattr(exposure_module.time, "monotonic", lambda: tick)
    assessment = Mock()
    before = deepcopy(session.__dict__, {id(session.lock): session.lock})

    with pytest.raises(ValueError):
        session.apply_answer("clicked", assessment)

    assert session.__dict__ == before
    assessment.rescore.assert_not_called()


def test_apply_answer_accepts_immediately_before_expiry(pending, exposure_module, monkeypatch):
    session, service, _, _, _ = pending
    monkeypatch.setattr(exposure_module.time, "monotonic", lambda: session.expires_at - 0.001)
    assert session.apply_answer("clicked", service)["score"] == 80


@pytest.mark.parametrize("failure", ["rescore", "stored_copy", "returned_copy"])
def test_apply_answer_stages_all_results_before_mutating_state(pending, failure):
    session, _, _, record, snapshot = pending
    before = deepcopy((session.__dict__, record, snapshot), {id(session.lock): session.lock})
    identities = dict(session.__dict__)
    error = RuntimeError("re-score failed")
    copies = 0

    class Uncopyable:
        def __deepcopy__(self, memo):
            nonlocal copies
            copies += 1
            if failure == "stored_copy" or copies == 2:
                raise error
            return self

    def rescore(working_record, working_findings):
        working_record["metadata"]["labels"].clear()
        working_findings["details"]["labels"].clear()
        if failure == "rescore":
            raise error
        return {"nested": Uncopyable()}

    assessment = Mock()
    assessment.rescore.side_effect = rescore
    with pytest.raises(RuntimeError) as raised:
        session.apply_answer("password", assessment)

    assert raised.value is error
    assert (session.__dict__, record, snapshot) == before
    assert all(session.__dict__[key] is value for key, value in identities.items())


def test_apply_answer_isolates_collaborator_result_and_returned_payload(pending):
    session, _, _, record, snapshot = pending
    before = deepcopy((session.record, session.findings, record, snapshot))
    retained = {}

    def rescore(working_record, working_findings):
        retained.update(record=working_record, findings=working_findings)
        return retained

    assessment = Mock()
    assessment.rescore.side_effect = rescore
    result = session.apply_answer("clicked", assessment)
    stored_before = deepcopy(session.result)
    retained["record"]["metadata"]["labels"].append("collaborator")
    result["findings"]["details"]["labels"].append("caller")

    assert session.result == stored_before
    assert result["record"]["metadata"]["labels"] == ["original"]
    assert retained["findings"]["details"]["labels"] == ["original"]
    assert (session.record, session.findings, record, snapshot) == before
    assert session.exposure["clicked"] is True
    assessment.assess.assert_not_called()


def test_apply_answer_scores_unknown_groups_without_stale_record_exposure(pending):
    session, service, ai, _, _ = pending
    session.record.update(clicked=True, downloaded=True, submitted_category="password")
    original = deepcopy(session.record)

    assert session.apply_answer("no_disclosure", service)["score"] == 60
    assert session.exposure == {
        "clicked": None, "downloaded": None,
        "submitted_category": None, "disclosure_answered": True,
    }
    assert session.record == original
    ai.assess.assert_called_once()


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
    exposure_module, inputs, prior_answer
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


def test_session_preserves_ownership_and_starts_unsaved_without_reply(exposure_module, inputs):
    session = exposure_module.ExposureSession(
        *inputs, chat_id=-1001234567890, user_id=202, message_id=303
    )

    assert (session.chat_id, session.user_id, session.message_id) == (-1001234567890, 202, 303)
    assert session.reply_message_id is None
    assert session.completed is False
    assert session.saved is False
    assert session.report is None
    assert isinstance(session.lock, asyncio.Lock)
    assert not session.lock.locked()


def test_sessions_keep_answers_payloads_and_lifecycle_independent(exposure_module, inputs):
    first = exposure_module.ExposureSession(*inputs, chat_id=101, user_id=202, message_id=303)
    second = exposure_module.ExposureSession(*inputs, chat_id=101, user_id=202, message_id=304)
    second_before = deepcopy((second.record, second.findings, second.result, second.exposure))

    first.record["metadata"]["labels"].append("changed")
    first.findings["details"]["labels"].append("changed")
    first.result["reasons"][0]["labels"].append("changed")
    first.exposure.update(clicked=True, submitted_category="otp", disclosure_answered=True)
    first.reply_message_id = 404
    first.completed = True
    first.saved = True
    first.report = {"result": first.result}

    assert (second.record, second.findings, second.result, second.exposure) == second_before
    assert first.lock is not second.lock
    assert not second.lock.locked()
    assert second.reply_message_id is None
    assert second.completed is False
    assert second.saved is False
    assert second.report is None


def test_session_lifetime_is_thirty_minutes_from_monotonic_creation(
    exposure_module, inputs, monkeypatch
):
    ticks = iter([1234.5, 1276.25])
    monkeypatch.setattr(exposure_module.time, "monotonic", lambda: next(ticks))

    first = exposure_module.ExposureSession(*inputs, chat_id=101, user_id=202, message_id=303)
    second = exposure_module.ExposureSession(*inputs, chat_id=101, user_id=202, message_id=304)

    assert first.created_at == 1234.5
    assert first.expires_at == 3034.5
    assert second.created_at == 1276.25
    assert second.expires_at == 3076.25


def test_session_token_is_urlsafe_and_fits_future_callback_payload(exposure_module, inputs):
    session = exposure_module.ExposureSession(*inputs, chat_id=101, user_id=202, message_id=303)

    assert re.fullmatch(r"[A-Za-z0-9_-]{16}", session.token)
    assert len(f"exposure:{session.token}:finish".encode("utf-8")) < 64
