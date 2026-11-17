"""Transport save paths produce unchanged, canonical Report snapshots offline."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from phishreport.assessment import AssessmentService
from phishreport.bot.handlers import TelegramIOManager
from phishreport.bot.messages import ChatRecordBuilder
from phishreport.cli.main import PhishReportApp
from phishreport.data import DataManager, JsonReportStorage, SqliteReportStorage
from phishreport.logic import LogicManager
from phishreport.model import Report

MESSAGE = "Verify your password at https://example.test/login and open invoice.pdf"
FINDINGS = {"suspicious": True, "credential_request": True, "insufficient_context": False}


@pytest.fixture(params=[JsonReportStorage, SqliteReportStorage], ids=["json", "sqlite"])
def data_manager(request, tmp_path):
    """Use real validation and persistence, isolated from application history."""
    return DataManager(request.param(tmp_path / "reports"))


def _update(text=None, message_id=100):
    return SimpleNamespace(
        effective_chat=SimpleNamespace(id=12345, type="private"),
        effective_user=SimpleNamespace(id=42),
        callback_query=None,
        effective_message=SimpleNamespace(
            text=text, message_id=message_id,
            reply_text=AsyncMock(return_value=SimpleNamespace(message_id=1100)),
        ),
    )


def _callback(session, action):
    update = _update(message_id=session.reply_message_id)
    update.callback_query = SimpleNamespace(
        data=f"exposure:{session.token}:{action}",
        answer=AsyncMock(), edit_message_text=AsyncMock(),
    )
    return update


def test_cli_saved_plain_report_round_trips_with_the_displayed_identifier(data_manager):
    ai = Mock(**{"assess.return_value": FINDINGS})
    io = Mock()
    app = PhishReportApp(io, ai, LogicManager(), data_manager)

    app.check_message(ChatRecordBuilder().build(MESSAGE))

    saved, = data_manager.load(strict=True)
    displayed = io.display_result.call_args.args[0]
    report = Report.from_legacy(saved)
    assert report.to_dict() == saved
    assert type(saved) is dict
    assert report.schema_version == 3
    assert report.assessment_id == displayed["assessment_id"]
    assert report.assessment_id
    assert "assessment_id" not in saved["result"]
    assert set(saved) == {"schema_version", "assessment_id", "channel", "message", "result"}
    assert report.channel == "chat"
    assert report.message == MESSAGE
    assert (report.result.score, report.result.priority) == (60, "MEDIUM")
    assert report.has_nested_exposure is False
    ai.assess.assert_called_once()
    io.display_result.assert_called_once()


@pytest.mark.parametrize(
    "actions,expected_score,expected_priority,expected_exposure",
    [
        pytest.param(
            ("clicked",), 80, "HIGH",
            {"clicked": True, "downloaded": None,
             "submitted_category": None, "disclosure_answered": False},
            id="clicked",
        ),
        pytest.param(
            ("password",), 90, "HIGH",
            {"clicked": None, "downloaded": None,
             "submitted_category": "password", "disclosure_answered": True},
            id="password",
        ),
        pytest.param(
            ("clicked", "password"), 90, "HIGH",
            {"clicked": True, "downloaded": None,
             "submitted_category": "password", "disclosure_answered": True},
            id="both",
        ),
    ],
)
def test_telegram_saved_exposure_report_round_trips_after_follow_up(
    data_manager, actions, expected_score, expected_priority, expected_exposure,
):
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager = TelegramIOManager(
        data_manager, allowed_chat_id=12345,
        assessment=AssessmentService(ai, LogicManager()),
    )

    async def scenario():
        await manager.assess_message(_update(MESSAGE), None)
        session, = manager._sessions.values()
        initial, = data_manager.load(strict=True)
        assert initial["result"]["priority"] == "MEDIUM"
        assert initial["result"]["score"] == 60
        assert initial["assessment_id"] == session.assessment_id

        for action in actions:
            await manager.exposure_callback(_callback(session, action), None)
        assert session.saved
        saved = data_manager.load(strict=True)[-1]
        # A replayed answer keeps the same revision and saves nothing new.
        await manager.exposure_callback(_callback(session, actions[-1]), None)
        assert data_manager.load(strict=True)[-1] == saved
        assert len(data_manager.load(strict=True)) == 1 + len(actions)
        return initial, saved

    initial, saved = asyncio.run(scenario())
    assert Report.from_legacy(initial).to_dict() == initial
    report = Report.from_legacy(saved)
    assert report.to_dict() == saved
    assert type(saved) is dict
    assert report.schema_version == 3
    assert report.assessment_id == initial["assessment_id"]
    assert "assessment_id" not in saved["result"]
    assert report.channel == "chat"
    assert report.message == MESSAGE
    assert (report.has_link, report.link) == (True, "https://example.test/login")
    assert (report.has_file, report.file_name) == (True, "invoice.pdf")
    assert report.has_nested_exposure is True
    assert saved["exposure"] == expected_exposure
    for field, value in expected_exposure.items():
        assert getattr(report.exposure, field) == value
    assert (report.result.score, report.result.priority) == (
        expected_score, expected_priority,
    )
    ai.assess.assert_called_once()
