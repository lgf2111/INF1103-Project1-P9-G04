"""Gmail linking and background email checks, with fake mailboxes and no network."""

import asyncio
import os
import ssl
import stat
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from phishreport.assessment import AssessmentService
from phishreport.bot.gmail import (
    AccountStore,
    EmailSource,
    GmailMailbox,
    LinkedAccount,
    MailboxError,
)
from phishreport.bot.gmail_handlers import GmailLinkHandlers
from phishreport.bot.monitor import EmailMonitor, Handled, Outcome
from phishreport.data import DataManager, JsonReportStorage
from phishreport.errors import AIUnavailable, StorageFailure
from phishreport.feedback import FeedbackService, FeedbackStore
from phishreport.logic import LogicManager

PHISHING = {"suspicious": True, "credential_request": True, "insufficient_context": False}
RAW = (
    b"From: bank@example.test\r\nSubject: Verify <now>\r\n"
    b"Message-ID: <abc123@mail.example.test>\r\n\r\nVerify your password now."
)


class FakeMailbox:
    def __init__(self, emails=(), error=None, newest=7):
        self.emails, self.error, self.newest, self.asked = list(emails), error, newest, []

    def latest_uid(self):
        if self.error:
            raise self.error
        return self.newest

    def unread(self, limit):
        if self.error:
            raise self.error
        return self.emails

    def new_since(self, last_uid):
        self.asked.append(last_uid)
        if self.error:
            raise self.error
        return self.emails


def update(chat_id=1):
    chat = SimpleNamespace(id=chat_id, send_message=AsyncMock())
    message = SimpleNamespace(reply_text=AsyncMock(), delete=AsyncMock())
    return SimpleNamespace(effective_chat=chat, effective_message=message)


def test_store_keeps_the_password_private_and_round_trips(tmp_path):
    store = AccountStore(tmp_path / "gmail.json")
    store.save(LinkedAccount(1, "a@gmail.com", "secret", 5))

    assert store.get(1) == LinkedAccount(1, "a@gmail.com", "secret", 5)
    assert stat.S_IMODE(os.stat(tmp_path / "gmail.json").st_mode) == 0o600
    assert store.remove(1) is True and store.remove(1) is False and store.all() == []


def test_gmail_connection_verifies_certificates_and_hostname(monkeypatch):
    connection = Mock()
    transport = Mock(return_value=connection)
    monkeypatch.setattr("phishreport.bot.gmail.imaplib.IMAP4_SSL", transport)

    assert GmailMailbox("example@example.test", "password")._connect() is connection

    context = transport.call_args.kwargs["ssl_context"]
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    connection.login.assert_called_once_with("example@example.test", "password")
    connection.select.assert_called_once_with("INBOX", readonly=True)


def test_certificate_rejection_is_retryable(monkeypatch):
    rejected = ssl.SSLCertVerificationError("simulated untrusted certificate")
    transport = Mock(side_effect=rejected)
    monkeypatch.setattr("phishreport.bot.gmail.imaplib.IMAP4_SSL", transport)

    with pytest.raises(MailboxError) as detected:
        GmailMailbox("example@example.test", "password").latest_uid()

    assert detected.value.retryable
    assert detected.value.__cause__ is rejected


def test_legacy_link_cursor_updates_are_monotonic(tmp_path):
    path = tmp_path / "gmail.json"
    path.write_text(
        '{"1": {"chat_id": 1, "address": "a@gmail.com", "password": "x", "last_uid": 5}}',
        encoding="utf-8",
    )
    store = AccountStore(path)
    legacy = store.get(1)

    assert store.advance_cursor(legacy, 10)
    assert store.advance_cursor(legacy, 8)
    assert store.get(1).last_uid == 10


def test_link_verifies_login_deletes_the_message_and_saves_from_now(tmp_path):
    store = AccountStore(tmp_path / "g.json")
    seen = {}

    def factory(address, password):
        seen["login"] = (address, password)
        return FakeMailbox(newest=42)

    handlers = GmailLinkHandlers(store, lambda u: True, factory)
    up = update()
    context = SimpleNamespace(args=["Me@Gmail.com", "abcd", "efgh", "ijkl", "mnop"])

    asyncio.run(handlers.link(up, context))

    assert seen["login"] == ("me@gmail.com", "abcdefghijklmnop")
    up.effective_message.delete.assert_awaited()
    assert store.get(1).last_uid == 42
    assert "Linked me@gmail.com" in up.effective_chat.send_message.call_args.args[0]


def test_link_without_arguments_explains_how_and_saves_nothing(tmp_path):
    store = AccountStore(tmp_path / "g.json")
    up = update()

    asyncio.run(GmailLinkHandlers(store, lambda u: True).link(up, SimpleNamespace(args=[])))

    assert "app password" in up.effective_message.reply_text.call_args.args[0]
    assert store.all() == []


def test_link_reports_a_rejected_login_and_saves_nothing(tmp_path):
    store = AccountStore(tmp_path / "g.json")
    factory = lambda a, p: FakeMailbox(error=MailboxError("Gmail rejected it.", False))  # noqa: E731
    up = update()

    asyncio.run(
        GmailLinkHandlers(store, lambda u: True, factory).link(
            up, SimpleNamespace(args=["a@gmail.com", "bad"])
        )
    )

    assert "app password" in up.effective_chat.send_message.call_args.args[0]
    assert store.all() == []


def test_unlink_deletes_the_saved_account(tmp_path):
    store = AccountStore(tmp_path / "g.json")
    store.save(LinkedAccount(1, "a@gmail.com", "x", 0))
    up = update()

    asyncio.run(GmailLinkHandlers(store, lambda u: True).unlink(up, SimpleNamespace(args=[])))

    assert store.all() == []


def monitor_for(tmp_path, mailbox, findings=PHISHING):
    store = AccountStore(tmp_path / "g.json")
    store.save(LinkedAccount(1, "a@gmail.com", "x", 5))
    bot, data = SimpleNamespace(send_message=AsyncMock()), Mock(spec=DataManager)
    service = AssessmentService(Mock(**{"assess.return_value": findings}), LogicManager())
    monitor = EmailMonitor(
        bot, store, service, data, asyncio.Lock(), mailbox_factory=lambda a, p: mailbox
    )
    return monitor, store, bot, data


def test_a_phishing_email_is_saved_and_alerted_and_marked_handled(tmp_path):
    monitor, store, bot, data = monitor_for(tmp_path, FakeMailbox([(9, RAW)]))

    asyncio.run(monitor.poll_once())

    sent = bot.send_message.call_args.kwargs
    assert "<b>From:</b> bank@example.test" in sent["text"]
    assert "<b>Subject:</b> Verify &lt;now&gt;" in sent["text"]
    assert "authuser=a%40gmail.com#search/rfc822msgid%3Aabc123%40mail.example.test" in sent["text"]
    assert sent["parse_mode"] == "HTML"
    assert sent["chat_id"] == 1
    assert data.save.call_args.args[0]["channel"] == "email"
    assert store.get(1).last_uid == 9


def test_saved_gmail_alert_offers_feedback_for_its_report(tmp_path):
    account_store = AccountStore(tmp_path / "g.json")
    account_store.save(LinkedAccount(1, "a@gmail.com", "x", 5))
    data_manager = DataManager(JsonReportStorage(tmp_path / "reports.json"))
    feedback_service = FeedbackService(FeedbackStore(tmp_path / "feedback.json"))
    bot = SimpleNamespace(send_message=AsyncMock())
    monitor = EmailMonitor(
        bot,
        account_store,
        AssessmentService(Mock(**{"assess.return_value": PHISHING}), LogicManager()),
        data_manager,
        asyncio.Lock(),
        mailbox_factory=lambda address, password: FakeMailbox([(9, RAW)]),
        feedback_service=feedback_service,
    )

    asyncio.run(monitor.poll_once())

    [report] = data_manager.load(strict=True)
    button = bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard[0][0]
    assert button.callback_data == f"fb:o:{report['assessment_id']}"


def test_a_safe_email_is_saved_without_an_alert(tmp_path):
    safe = {"suspicious": False, "credential_request": False, "insufficient_context": False}
    monitor, store, bot, data = monitor_for(tmp_path, FakeMailbox([(9, RAW)]), safe)

    asyncio.run(monitor.poll_once())

    bot.send_message.assert_not_awaited()
    data.save.assert_called_once()
    assert store.get(1).last_uid == 9


def test_a_temporary_ai_failure_keeps_the_email_for_the_next_cycle(tmp_path):
    monitor, store, bot, _ = monitor_for(tmp_path, FakeMailbox([(9, RAW)]))
    monitor._assessment = Mock(assess=Mock(side_effect=AIUnavailable()))

    asyncio.run(monitor.poll_once())

    bot.send_message.assert_not_awaited()
    assert store.get(1).last_uid == 5


def test_a_rejected_login_unlinks_and_tells_the_user(tmp_path):
    mailbox = FakeMailbox(error=MailboxError("rejected", False))
    monitor, store, bot, _ = monitor_for(tmp_path, mailbox)

    asyncio.run(monitor.poll_once())

    assert store.all() == []
    assert "unlinked" in bot.send_message.call_args.kwargs["text"]


def test_a_network_failure_keeps_the_account_and_retries(tmp_path):
    monitor, store, bot, _ = monitor_for(tmp_path, FakeMailbox(error=MailboxError("net")))

    asyncio.run(monitor.poll_once())

    assert store.get(1) is not None
    bot.send_message.assert_not_awaited()


@pytest.mark.parametrize("manual", [False, True])
@pytest.mark.parametrize("relink", [False, True])
def test_inflight_check_cannot_restore_unlinked_or_replace_relinked_account(
    tmp_path, manual, relink,
):
    monitor, store, _, _ = monitor_for(tmp_path, FakeMailbox([(9, RAW)]))
    handlers = GmailLinkHandlers(store, lambda _: True, lambda *_: FakeMailbox(newest=5))
    original = store.get(1)

    async def finish_after_unlink(_account, _raw):
        await handlers.unlink(update(), SimpleNamespace(args=[]))
        if relink:
            await handlers.link(update(), SimpleNamespace(args=["a@gmail.com", "x"]))
        return Handled(Outcome.SENT)

    monitor._handle = finish_after_unlink
    reply = asyncio.run(monitor.check_unread(1) if manual else monitor.poll_once())

    if manual:
        assert "Gmail link changed" in reply
    if relink:
        replacement = store.get(1)
        assert replacement.link_id != original.link_id
        assert replacement.last_uid == 5
    else:
        assert store.get(1) is None


def test_unlink_during_ai_check_discards_the_old_result(tmp_path):
    monitor, store, bot, data = monitor_for(tmp_path, FakeMailbox([(9, RAW)]))
    assess = monitor._assessment.assess

    def finish_after_unlink(record):
        assert store.remove(1)
        return assess(record)

    monitor._assessment.assess = finish_after_unlink
    asyncio.run(monitor.poll_once())

    assert store.get(1) is None
    data.save.assert_not_called()
    bot.send_message.assert_not_awaited()


def test_login_failure_from_old_poll_does_not_remove_replacement(tmp_path):
    mailbox = FakeMailbox()
    monitor, store, bot, _ = monitor_for(tmp_path, mailbox)

    def reject_after_relink(_last_uid):
        store.save(LinkedAccount(1, "a@gmail.com", "x", 20))
        raise MailboxError("old login rejected", False)

    mailbox.new_since = reject_after_relink
    asyncio.run(monitor.poll_once())

    assert store.get(1).last_uid == 20
    bot.send_message.assert_not_awaited()


def test_alert_is_html_escaped_and_clipped():
    from phishreport.bot.messages import PhishingAlertFormatter

    result = {
        "priority": "HIGH",
        "score": 90,
        "matched_rule": "DisclosureRule",
        "trace": [
            {"rule_name": "DisclosureRule", "matched": True, "score": 90},
        ],
        "reasons": ["<script>x</script> " + "a" * 500],
        "checklist": [f"step {n}" for n in range(9)],
    }

    text = PhishingAlertFormatter().format(result, "Evil <e@x.test>", "", None)

    assert "🚨 <b>HIGH risk</b>" in text
    assert "&lt;script&gt;" in text and "<script>" not in text
    assert "Evil &lt;e@x.test&gt;" in text
    assert "Matched rule:</b> DisclosureRule" in text
    assert "DisclosureRule: matched (score: 90)" in text
    assert "5. step 4" in text and "6. step 5" not in text
    assert "Open the email" not in text
    assert "..." in text


def test_email_source_without_message_id_has_no_link():
    source = EmailSource(b"Subject: Hi\r\n\r\nBody")

    assert source.subject == "Hi"
    assert source.gmail_url("a@gmail.com") is None


def test_checkmail_assesses_unread_mail_and_summarises(tmp_path):
    monitor, store, bot, data = monitor_for(tmp_path, FakeMailbox([(9, RAW), (11, RAW)]))

    reply = asyncio.run(monitor.check_unread(1))

    assert reply == "Checked 2 unread email(s): 2 flagged, 0 looked fine."
    assert bot.send_message.await_count == 2
    assert store.get(1).last_uid == 5  # Only the poller moves the cursor.
    assert store.get(1).handled == [9, 11]


def test_checkmail_with_nothing_unread_or_nothing_linked(tmp_path):
    monitor, _, _, _ = monitor_for(tmp_path, FakeMailbox([]))

    assert asyncio.run(monitor.check_unread(1)) == "No unread emails to check."
    assert "linkgmail" in asyncio.run(monitor.check_unread(999))


def test_checkmail_command_replies_with_the_summary(tmp_path):
    monitor, _, _, _ = monitor_for(tmp_path, FakeMailbox([]))
    handlers = GmailLinkHandlers(AccountStore(tmp_path / "g.json"), lambda u: True)
    up = update()
    context = SimpleNamespace(application=SimpleNamespace(bot_data={"monitor": monitor}))

    asyncio.run(handlers.check(up, context))

    assert up.effective_message.reply_text.call_args.args[0] == "No unread emails to check."


def test_one_unexpected_error_retries_that_email_and_keeps_the_cursor(tmp_path):
    monitor, store, bot, _ = monitor_for(tmp_path, FakeMailbox([(9, RAW), (10, RAW)]))
    calls = iter([KeyError("boom"), PHISHING, PHISHING])

    def assess(record):
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monitor._assessment = AssessmentService(Mock(assess=assess), LogicManager())

    asyncio.run(monitor.poll_once())

    assert bot.send_message.await_count == 0 and store.get(1).last_uid == 5

    asyncio.run(monitor.poll_once())

    assert bot.send_message.await_count == 2
    assert store.get(1).last_uid == 10


def test_polling_a_healthy_inbox_prints_no_failure(tmp_path, capsys):
    monitor, _, _, _ = monitor_for(tmp_path, FakeMailbox([]))
    monitor._interval = 0

    async def two_cycles():
        task = asyncio.create_task(monitor.run())
        await asyncio.sleep(0.05)
        task.cancel()

    asyncio.run(two_cycles())

    assert "failed" not in capsys.readouterr().out


@pytest.mark.parametrize("retryable", [True, False])
def test_mailbox_failures_never_render_private_text(tmp_path, capsys, retryable):
    mailbox = FakeMailbox(error=MailboxError("PRIVATE credentials", retryable))
    monitor, store, bot, _ = monitor_for(tmp_path, mailbox)
    reply = asyncio.run(monitor.check_unread(1))
    assert "PRIVATE" not in reply
    asyncio.run(monitor.poll_once())
    assert "PRIVATE" not in capsys.readouterr().out
    up = update()
    asyncio.run(GmailLinkHandlers(store, lambda u: True, lambda a, p: mailbox).link(
        up, SimpleNamespace(args=["a@gmail.com", "password"]),
    ))
    assert "PRIVATE" not in up.effective_chat.send_message.call_args.args[0]


@pytest.mark.parametrize("operation", ["link", "unlink", "check"])
@pytest.mark.parametrize("error_type", [OSError, ValueError])
def test_account_storage_failures_get_safe_replies(operation, error_type):
    store = Mock()
    error = error_type("PRIVATE storage path")
    store.save.side_effect = error
    store.remove.side_effect = error
    store.revoke.side_effect = error
    store.get.side_effect = error
    up = update()
    handlers = GmailLinkHandlers(store, lambda u: True, lambda a, p: FakeMailbox())
    monitor = EmailMonitor(Mock(), store, Mock(), Mock(), asyncio.Lock())
    context = SimpleNamespace(args=["a@gmail.com", "password"],
        application=SimpleNamespace(bot_data={"monitor": monitor}))
    asyncio.run(getattr(handlers, operation)(up, context))
    replies = (up.effective_chat.send_message.call_args_list if operation == "link"
               else up.effective_message.reply_text.call_args_list)
    final = replies[-1].args[0]
    assert "PRIVATE" not in final
    assert "try again" in final.lower()
    assert "Linked" not in final and "unlinked" not in final


@pytest.mark.parametrize("manual", [False, True])
def test_progress_save_failure_retains_in_memory_uid(tmp_path, manual):
    monitor, store, _, _ = monitor_for(tmp_path, FakeMailbox([(9, RAW)]))
    account = store.get(1)
    failing = "mark_handled" if manual else "advance_cursor"
    monitor._store = Mock(wraps=store, **{f"{failing}.side_effect": OSError("PRIVATE progress")})
    asyncio.run(monitor.check_unread(1) if manual else monitor._poll_account(account))
    getattr(monitor._store, failing).assert_called_once_with(
        account, [9] if manual else 9
    )
    assert account.last_uid == 5
    assert store.get(1).last_uid == 5


def test_unlink_during_inflight_assessment_delivers_no_alert(tmp_path):
    monitor, store, bot, data = monitor_for(tmp_path, FakeMailbox([(9, RAW)]))
    handlers = GmailLinkHandlers(store, lambda _: True)
    saving, release = threading.Event(), threading.Event()

    def hold_the_save(_report):
        saving.set()
        release.wait(5)

    data.save.side_effect = hold_the_save

    async def scenario():
        poll = asyncio.create_task(monitor.poll_once())
        await asyncio.to_thread(saving.wait, 5)
        await handlers.unlink(update(), SimpleNamespace(args=[]))
        release.set()
        await poll

    asyncio.run(scenario())

    bot.send_message.assert_not_awaited()
    assert store.get(1) is None


def test_unlink_waits_for_an_alert_already_being_sent(tmp_path):
    monitor, store, bot, _ = monitor_for(tmp_path, FakeMailbox([(9, RAW)]))
    handlers = GmailLinkHandlers(store, lambda _: True)
    events = []

    async def scenario():
        sending, release = asyncio.Event(), asyncio.Event()

        async def slow_send(**_options):
            sending.set()
            await release.wait()
            events.append("sent")

        bot.send_message = slow_send
        poll = asyncio.create_task(monitor.poll_once())
        await sending.wait()
        unlink = asyncio.create_task(handlers.unlink(update(), SimpleNamespace(args=[])))
        await asyncio.sleep(0.05)
        assert not unlink.done() and store.get(1) is None  # revoked, not yet removed
        release.set()
        await unlink
        events.append("unlinked")
        await poll

    asyncio.run(scenario())

    assert events == ["sent", "unlinked"]
    assert store.all() == []


@pytest.mark.parametrize("content", [b"{not json", b"[1, 2]", b'{"1": "oops"}', b"\xff\xfe"])
def test_link_refuses_to_overwrite_a_corrupt_account_file(tmp_path, content):
    path = tmp_path / "g.json"
    path.write_bytes(content)
    store = AccountStore(path)
    up = update()

    asyncio.run(GmailLinkHandlers(store, lambda u: True, lambda a, p: FakeMailbox()).link(
        up, SimpleNamespace(args=["a@gmail.com", "password"]),
    ))

    assert "Could not save the Gmail link" in up.effective_chat.send_message.call_args.args[0]
    with pytest.raises(StorageFailure):
        store.save(LinkedAccount(1, "a@gmail.com", "x", 0))
    assert path.read_bytes() == content


def test_a_parse_error_is_not_an_empty_account_list(tmp_path):
    path = tmp_path / "g.json"
    path.write_text('{"1": {"chat_id": 1,')
    store = AccountStore(path)

    for read in (store.all, lambda: store.get(1), lambda: store.remove(1)):
        with pytest.raises(StorageFailure):
            read()
    assert path.read_text() == '{"1": {"chat_id": 1,'


def test_a_missing_account_file_is_an_empty_list(tmp_path):
    assert AccountStore(tmp_path / "none.json").all() == []


def test_unlinking_twice_is_a_no_op_with_the_same_message(tmp_path):
    store = AccountStore(tmp_path / "g.json")
    store.save(LinkedAccount(1, "a@gmail.com", "x", 0))
    handlers = GmailLinkHandlers(store, lambda _: True)
    replies = []
    for _ in range(3):
        up = update()
        asyncio.run(handlers.unlink(up, SimpleNamespace(args=[])))
        replies.append(up.effective_message.reply_text.call_args.args[0])

    assert "unlinked" in replies[0]
    assert replies[1] == replies[2] == "No Gmail account is linked to this chat."
    assert store.all() == []


def test_link_poll_alert_unlink_works_end_to_end(tmp_path):
    monitor, store, bot, _ = monitor_for(tmp_path, FakeMailbox([(9, RAW)]))
    handlers = GmailLinkHandlers(store, lambda _: True, lambda a, p: FakeMailbox(newest=5))
    up = update()

    asyncio.run(handlers.link(up, SimpleNamespace(args=["a@gmail.com", "x"])))
    asyncio.run(monitor.poll_once())
    asyncio.run(handlers.unlink(up, SimpleNamespace(args=[])))
    asyncio.run(monitor.poll_once())

    assert bot.send_message.await_count == 1
    assert store.all() == []
    assert "unlinked" in up.effective_message.reply_text.call_args.args[0]


def test_unlink_between_save_and_send_delivers_nothing_and_keeps_the_cursor(tmp_path):
    monitor, store, bot, data = monitor_for(tmp_path, FakeMailbox([(9, RAW)]))
    handlers = GmailLinkHandlers(store, lambda _: True)
    saved, at_send_gate, revoked = (
        threading.Event(), threading.Event(), threading.Event()
    )
    release_gate = threading.Event()
    advance_cursor = Mock(wraps=store.advance_cursor)
    store.advance_cursor = advance_cursor
    real_is_current = store.is_current
    checks = {"count": 0}

    def gated_is_current(account):
        checks["count"] += 1
        if checks["count"] == 2:  # The check inside the delivery lock, after saving.
            at_send_gate.set()
            release_gate.wait(5)
        return real_is_current(account)

    real_revoke = store.revoke

    def observed_revoke(chat_id):
        result = real_revoke(chat_id)
        revoked.set()
        return result

    store.is_current = gated_is_current
    store.revoke = observed_revoke
    data.save.side_effect = lambda _report: saved.set()

    async def scenario():
        poll = asyncio.create_task(monitor.poll_once())
        assert await asyncio.to_thread(saved.wait, 5)
        assert await asyncio.to_thread(at_send_gate.wait, 5)
        unlink = asyncio.create_task(handlers.unlink(update(), SimpleNamespace(args=[])))
        assert await asyncio.to_thread(revoked.wait, 5)
        release_gate.set()
        await poll
        await unlink

    asyncio.run(scenario())

    assert data.save.call_count == 1  # The report was saved before the unlink landed.
    bot.send_message.assert_not_awaited()
    advance_cursor.assert_not_called()
    assert monitor._pending == {}
    assert store.all() == []
