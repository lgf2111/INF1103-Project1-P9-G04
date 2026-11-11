"""Pending exposure session state is isolated without bot or AI I/O."""

import asyncio
import importlib
import re
from copy import deepcopy

import pytest

from phishreport.assessment import AssessmentSnapshot


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
