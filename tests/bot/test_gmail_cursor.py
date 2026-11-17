"""The Gmail cursor only moves past mail that was fully handled, with no network."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from phishreport.assessment import AssessmentService
from phishreport.bot.gmail import (
    AccountStore,
    FetchRejected,
    GmailMailbox,
    LinkedAccount,
    MailboxError,
)
from phishreport.bot.monitor import EmailMonitor
from phishreport.data import DataManager
from phishreport.errors import StorageFailure
from phishreport.logic import LogicManager

PHISHING = {"suspicious": True, "credential_request": True, "insufficient_context": False}


def raw(uid: int) -> bytes:
    return (
        f"From: bank@example.test\r\nSubject: Verify {uid}\r\n\r\nVerify your password {uid}."
    ).encode()


class Inbox:
    """Fake mailbox that honours the cursor like IMAP, so a retry sees the same mail."""

    def __init__(self, uids, unread=()):
        self.uids, self._unread = list(uids), list(unread)

    def new_since(self, last_uid):
        return [(uid, raw(uid)) for uid in self.uids if uid > last_uid]

    def unread(self, limit):
        return [(uid, raw(uid)) for uid in self._unread]


def build(tmp_path, mailbox, cursor=5):
    store = AccountStore(tmp_path / "g.json")
    store.save(LinkedAccount(1, "a@gmail.com", "x", cursor))
    bot, data = SimpleNamespace(send_message=AsyncMock()), Mock(spec=DataManager)
    provider = Mock(**{"assess.return_value": PHISHING})
    monitor = EmailMonitor(
        bot, store, AssessmentService(provider, LogicManager()), data, asyncio.Lock(),
        mailbox_factory=lambda address, password: mailbox,
    )
    return monitor, store, bot, data, provider


def test_send_failure_keeps_the_cursor_and_retries_the_same_uid_once(tmp_path):
    monitor, store, bot, data, provider = build(tmp_path, Inbox([6]))
    bot.send_message.side_effect = RuntimeError("telegram down")

    asyncio.run(monitor.poll_once())

    assert store.get(1).last_uid == 5
    assert bot.send_message.await_count == 1

    bot.send_message.side_effect = None
    asyncio.run(monitor.poll_once())
    asyncio.run(monitor.poll_once())

    assert bot.send_message.await_count == 2  # One failed attempt, one retry, no third.
    assert store.get(1).last_uid == 6
    data.save.assert_called_once()  # The retry reuses the saved report.
    provider.assess.assert_called_once()


def test_save_failure_keeps_the_cursor_and_retries_the_same_uid_once(tmp_path):
    monitor, store, bot, data, provider = build(tmp_path, Inbox([6]))
    data.save.side_effect = StorageFailure()

    asyncio.run(monitor.poll_once())

    assert store.get(1).last_uid == 5
    bot.send_message.assert_not_awaited()

    data.save.side_effect = None
    asyncio.run(monitor.poll_once())
    asyncio.run(monitor.poll_once())

    assert data.save.call_count == 2  # One failed attempt, one retry, no third.
    assert bot.send_message.await_count == 1
    assert store.get(1).last_uid == 6
    provider.assess.assert_called_once()


class RejectingConnection:
    def __init__(self, uids, rejected):
        self.uids, self.rejected = uids, rejected

    def uid(self, command, *args):
        if command == "SEARCH":
            return "OK", [" ".join(map(str, self.uids)).encode()]
        uid = int(args[0])
        if uid in self.rejected:
            return "NO", [None]
        return "OK", [(b"1 (BODY[] {n})", raw(uid)), b")"]

    def logout(self):
        pass


def imap_mailbox(monkeypatch, uids, rejected):
    mailbox = GmailMailbox("a@gmail.com", "x")
    monkeypatch.setattr(mailbox, "_connect", lambda: RejectingConnection(uids, rejected))
    return mailbox


def test_rejected_fetch_raises_instead_of_returning_an_empty_message(monkeypatch):
    mailbox = imap_mailbox(monkeypatch, [6], rejected={6})

    with pytest.raises(FetchRejected) as raised:
        mailbox.new_since(5)

    assert raised.value.uid == 6 and isinstance(raised.value, MailboxError)
    with pytest.raises(FetchRejected):
        mailbox.unread()


def test_rejected_fetch_after_a_good_one_still_delivers_the_good_one(monkeypatch):
    mailbox = imap_mailbox(monkeypatch, [6, 7], rejected={7})

    assert [uid for uid, _ in mailbox.new_since(5)] == [6]
    with pytest.raises(FetchRejected):  # The next batch starts at the refused UID.
        mailbox.new_since(6)


def test_rejected_fetch_produces_no_assessment_and_keeps_the_cursor(tmp_path, monkeypatch):
    mailbox = imap_mailbox(monkeypatch, [6], rejected={6})
    monitor, store, bot, data, provider = build(tmp_path, mailbox)

    asyncio.run(monitor.poll_once())

    provider.assess.assert_not_called()
    data.save.assert_not_called()
    bot.send_message.assert_not_awaited()
    assert store.get(1).last_uid == 5


def test_happy_path_assesses_saves_delivers_and_advances_by_one(tmp_path):
    monitor, store, bot, data, provider = build(tmp_path, Inbox([6]))

    asyncio.run(monitor.poll_once())

    provider.assess.assert_called_once()
    data.save.assert_called_once()
    bot.send_message.assert_awaited_once()
    assert store.get(1).last_uid == 6


def test_checkmail_only_consumes_the_uids_it_processed(tmp_path):
    inbox = Inbox(uids=range(6, 13), unread=[9, 11, 12])
    monitor, store, bot, data, provider = build(tmp_path, inbox)

    reply = asyncio.run(monitor.check_unread(1))

    assert reply == "Checked 3 unread email(s): 3 flagged, 0 looked fine."
    assert store.get(1).last_uid == 5  # 6, 7, 8 and 10 were never seen by anyone.
    assert store.get(1).handled == [9, 11, 12]

    asyncio.run(monitor.poll_once())

    assert provider.assess.call_count == 3 + 4  # The poller handled only 6, 7, 8 and 10.
    assert store.get(1).last_uid == 12
    assert store.get(1).handled == []


def test_checkmail_never_moves_the_cursor_backwards(tmp_path):
    monitor, store, _, _, _ = build(tmp_path, Inbox([], unread=[9]), cursor=20)

    asyncio.run(monitor.check_unread(1))

    assert store.get(1).last_uid == 20
    assert store.get(1).handled == []
