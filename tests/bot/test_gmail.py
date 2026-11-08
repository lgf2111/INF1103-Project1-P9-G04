"""Gmail linking and background email checks, with fake mailboxes and no network."""

import asyncio
import os
import stat
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from phishreport.assessment import AssessmentService
from phishreport.bot.gmail import AccountStore, EmailSource, LinkedAccount, MailboxError
from phishreport.bot.gmail_handlers import GmailLinkHandlers
from phishreport.bot.monitor import EmailMonitor
from phishreport.data import DataManager
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


def test_a_safe_email_is_saved_without_an_alert(tmp_path):
    safe = {"suspicious": False, "credential_request": False, "insufficient_context": False}
    monitor, store, bot, data = monitor_for(tmp_path, FakeMailbox([(9, RAW)]), safe)

    asyncio.run(monitor.poll_once())

    bot.send_message.assert_not_awaited()
    data.save.assert_called_once()
    assert store.get(1).last_uid == 9


def test_a_temporary_ai_failure_keeps_the_email_for_the_next_cycle(tmp_path):
    monitor, store, bot, _ = monitor_for(tmp_path, FakeMailbox([(9, RAW)]))
    monitor._assessment = Mock(assess=Mock(side_effect=RuntimeError("down")))

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


def test_alert_is_html_escaped_and_clipped():
    from phishreport.bot.messages import PhishingAlertFormatter

    result = {
        "priority": "HIGH",
        "score": 90,
        "reasons": ["<script>x</script> " + "a" * 500],
        "checklist": [f"step {n}" for n in range(9)],
    }

    text = PhishingAlertFormatter().format(result, "Evil <e@x.test>", "", None)

    assert "🚨 <b>HIGH risk</b>" in text
    assert "&lt;script&gt;" in text and "<script>" not in text
    assert "Evil &lt;e@x.test&gt;" in text
    assert "5. step 4" in text and "6. step 5" not in text
    assert "Open the email" not in text
    assert "..." in text


def test_email_source_without_message_id_has_no_link():
    source = EmailSource(b"Subject: Hi\r\n\r\nBody")

    assert source.subject == "Hi"
    assert source.gmail_url("a@gmail.com") is None
