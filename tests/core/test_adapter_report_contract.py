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


@pytest.mark.parametrize("completion", ["finish", "skip"])
def test_telegram_saved_exposure_report_round_trips_after_completion(data_manager, completion):
    ai = Mock(**{"assess.return_value": FINDINGS})
    manager = TelegramIOManager(
        data_manager, allowed_chat_id=12345,
        assessment=AssessmentService(ai, LogicManager()),
    )

    async def scenario():
        await manager.assess_message(_update(MESSAGE), None)
        assert data_manager.load(strict=True) == []
        session, = manager._sessions.values()
        if completion == "finish":
            await manager.exposure_callback(_callback(session, "clicked"), None)
            await manager.exposure_callback(_callback(session, "password"), None)
            assert data_manager.load(strict=True) == []
        await manager.exposure_callback(_callback(session, completion), None)
        assert session.completed and session.saved
        frozen = session.report
        # Replayed completion must retain the frozen identifier and save only once.
        await manager.exposure_callback(_callback(session, completion), None)
        saved, = data_manager.load(strict=True)
        assert saved == frozen
        return saved

    saved = asyncio.run(scenario())
    report = Report.from_legacy(saved)
    assert report.to_dict() == saved
    assert type(saved) is dict
    assert report.schema_version == 3
    assert report.assessment_id
    assert "assessment_id" not in saved["result"]
    assert report.channel == "chat"
    assert report.message == MESSAGE
    assert (report.has_link, report.link) == (True, "https://example.test/login")
    assert (report.has_file, report.file_name) == (True, "invoice.pdf")
    assert report.has_nested_exposure is True
    expected = {
        "clicked": True if completion == "finish" else None,
        "downloaded": False if completion == "finish" else None,
        "submitted_category": "password" if completion == "finish" else None,
        "disclosure_answered": completion == "finish",
    }
    assert saved["exposure"] == expected
    for field, value in expected.items():
        assert getattr(report.exposure, field) == value
    assert (report.result.score, report.result.priority) == (
        (90, "HIGH") if completion == "finish" else (60, "MEDIUM")
    )
    ai.assess.assert_called_once()
