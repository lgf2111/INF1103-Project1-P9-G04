"""Link a Gmail account over IMAP and read the mail that arrives after linking."""

import asyncio
import imaplib
import json
import os
import re
import ssl
import tempfile
from dataclasses import asdict, dataclass, field, replace
from email import policy
from email.parser import BytesParser
from pathlib import Path
from threading import Lock
from urllib.parse import quote
from uuid import uuid4

from phishreport.errors import StorageFailure

IMAP_HOST = "imap.gmail.com"
ADDRESS_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class MailboxError(Exception):
    """The mailbox could not be read. `retryable` is False for a wrong login."""

    def __init__(self, message: str, retryable: bool = True) -> None:
        super().__init__(message)
        self.retryable = retryable


class FetchRejected(MailboxError):
    """Gmail refused to return one message, so its content is unknown, not empty."""

    def __init__(self, uid: int) -> None:
        super().__init__("Gmail did not return a message.")
        self.uid = uid


@dataclass
class LinkedAccount:
    """One Telegram chat linked to one Gmail address."""

    chat_id: int
    address: str
    password: str
    last_uid: int  # Only mail with a higher IMAP UID is checked.
    link_id: str | None = field(default=None, compare=False, repr=False)
    # UIDs above last_uid that /checkmail already handled; the poller skips them.
    handled: list[int] = field(default_factory=list, compare=False, repr=False)


class AccountStore:
    """Keep linked accounts in a JSON file that only the owner can read.

    The app password has to be stored to keep polling, so the file is created with
    mode 0600 and replaced atomically. It is never logged.

    A missing file is an empty list, but an unreadable or malformed one raises
    StorageFailure and is left untouched, so it is never overwritten by a new link.

    Unlinking first revokes the link: after `revoke` no delivery for it passes
    `is_current`. `delivery` serialises sends with unlinking, so an alert that is
    already being sent finishes before the credential is deleted.
    """

    def __init__(self, path: str | os.PathLike[str]) -> None:
        self._path = Path(path)
        self._lock = Lock()
        self._revoked: set[tuple[int, str | None]] = set()
        self._gates: dict[int, asyncio.Lock] = {}

    def _read(self) -> dict[str, dict]:
        try:
            with open(self._path, encoding="utf-8") as stream:
                data = json.load(stream)
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, UnicodeError) as error:
            raise StorageFailure() from error
        if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
            raise StorageFailure()
        return data

    def _write(self, data: dict[str, dict]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(dir=self._path.parent, prefix=".gmail-")
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(data, stream)
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def all(self) -> list[LinkedAccount]:
        with self._lock:
            data = self._read()
        accounts = []
        for value in data.values():
            try:
                account = LinkedAccount(**value)
            except TypeError:
                continue
            if (account.chat_id, account.link_id) not in self._revoked:
                accounts.append(account)
        return accounts

    def get(self, chat_id: int) -> LinkedAccount | None:
        return next((account for account in self.all() if account.chat_id == chat_id), None)

    @staticmethod
    def _matches_link(stored: object, account: LinkedAccount) -> bool:
        # Legacy accounts have no link_id. Relinking always assigns a fresh one.
        return (
            isinstance(stored, dict)
            and stored.get("chat_id") == account.chat_id
            and stored.get("link_id") == account.link_id
        )

    def is_current(self, account: LinkedAccount) -> bool:
        """Return whether this snapshot still belongs to the active link."""
        with self._lock:
            return (
                (account.chat_id, account.link_id) not in self._revoked
                and self._matches_link(self._read().get(str(account.chat_id)), account)
            )

    def revoke(self, chat_id: int) -> bool:
        """Stop the chat's active link from delivering anything. False if none is linked."""
        with self._lock:
            current = self._read().get(str(chat_id))
            if current is None:
                return False
            self._revoked.add((chat_id, current.get("link_id")))
            return True

    def delivery(self, chat_id: int) -> asyncio.Lock:
        """Return the lock held while an alert is sent and while the link is removed."""
        with self._lock:
            return self._gates.setdefault(chat_id, asyncio.Lock())

    def save(self, account: LinkedAccount) -> None:
        """Create or replace a link, even when the mailbox credentials match."""
        with self._lock:
            data = self._read()
            data[str(account.chat_id)] = asdict(replace(account, link_id=uuid4().hex))
            self._write(data)

    def advance_cursor(self, account: LinkedAccount, uid: int) -> bool:
        """Advance the active link's cursor. Return False for a stale snapshot."""
        with self._lock:
            data = self._read()
            current = data.get(str(account.chat_id))
            if not self._matches_link(current, account):
                return False
            if uid > current["last_uid"]:
                current["last_uid"] = uid
                current["handled"] = [h for h in current.get("handled", []) if h > uid]
                self._write(data)
            return True

    def mark_handled(self, account: LinkedAccount, uids: list[int]) -> bool:
        """Record UIDs handled out of order without moving the cursor.

        Return False for a stale snapshot. UIDs at or below the cursor are ignored.
        """
        with self._lock:
            data = self._read()
            current = data.get(str(account.chat_id))
            if not self._matches_link(current, account):
                return False
            merged = sorted(
                {*current.get("handled", []), *(u for u in uids if u > current["last_uid"])}
            )
            if merged != current.get("handled", []):
                current["handled"] = merged
                self._write(data)
            return True

    def is_handled(self, account: LinkedAccount, uid: int) -> bool:
        """Return whether /checkmail already handled this UID for the active link."""
        with self._lock:
            current = self._read().get(str(account.chat_id))
            return self._matches_link(current, account) and uid in current.get("handled", [])

    def remove(self, chat_id: int, *, expected: LinkedAccount | None = None) -> bool:
        """Remove a link, optionally requiring the caller's link to still be active."""
        with self._lock:
            data = self._read()
            key = str(chat_id)
            current = data.get(key)
            if current is None or (
                expected is not None and not self._matches_link(current, expected)
            ):
                return False
            del data[key]
            self._write(data)
            self._revoked.discard((chat_id, current.get("link_id")))
            return True


class GmailMailbox:
    """Read-only IMAP access to one Gmail inbox."""

    def __init__(self, address: str, password: str, host: str = IMAP_HOST) -> None:
        self._address = address
        self._password = password
        self._host = host

    def _connect(self) -> imaplib.IMAP4_SSL:
        try:
            connection = imaplib.IMAP4_SSL(
                self._host, ssl_context=ssl.create_default_context(), timeout=30,
            )
        except (OSError, imaplib.IMAP4.error) as error:
            raise MailboxError("Could not reach Gmail.") from error
        try:
            connection.login(self._address, self._password)
            connection.select("INBOX", readonly=True)  # Reading never marks mail as seen.
        except imaplib.IMAP4.error as error:
            self._close(connection)
            raise MailboxError("Gmail rejected the address or app password.", False) from error
        except OSError as error:
            self._close(connection)
            raise MailboxError("Could not reach Gmail.") from error
        return connection

    @staticmethod
    def _close(connection: imaplib.IMAP4_SSL) -> None:
        try:
            connection.logout()
        except (OSError, imaplib.IMAP4.error):
            pass

    @staticmethod
    def _uids(data) -> list[int]:
        return [int(uid) for uid in (data[0] or b"").split()]

    def latest_uid(self) -> int:
        """Return the newest UID in the inbox (0 if empty); also proves the login works."""
        connection = self._connect()
        try:
            status, data = connection.uid("SEARCH", "ALL")
            uids = self._uids(data) if status == "OK" else []
            return max(uids, default=0)
        except (OSError, imaplib.IMAP4.error) as error:
            raise MailboxError("Could not read the Gmail inbox.") from error
        finally:
            self._close(connection)

    def new_since(self, last_uid: int, limit: int = 10) -> list[tuple[int, bytes]]:
        """Return up to `limit` (uid, raw message) pairs newer than last_uid.

        Read state is ignored: opening or moving a message in Gmail marks it read, and
        the stored UID already prevents checking the same message twice. Raises
        FetchRejected if the oldest message cannot be fetched.
        """
        connection = self._connect()
        try:
            status, data = connection.uid("SEARCH", "UID", f"{last_uid + 1}:*")
            if status != "OK":
                raise MailboxError("Could not search the Gmail inbox.")
            # A "n:*" range always includes the newest message, even if it is older.
            uids = sorted(uid for uid in self._uids(data) if uid > last_uid)[:limit]
            return self._fetch(connection, uids)
        except (OSError, imaplib.IMAP4.error) as error:
            raise MailboxError("Could not read the Gmail inbox.") from error
        finally:
            self._close(connection)

    def unread(self, limit: int = 20) -> list[tuple[int, bytes]]:
        """Return the newest `limit` unread (uid, raw message) pairs, oldest first."""
        connection = self._connect()
        try:
            status, data = connection.uid("SEARCH", "UNSEEN")
            if status != "OK":
                raise MailboxError("Could not search the Gmail inbox.")
            return self._fetch(connection, sorted(self._uids(data))[-limit:])
        except (OSError, imaplib.IMAP4.error) as error:
            raise MailboxError("Could not read the Gmail inbox.") from error
        finally:
            self._close(connection)

    @staticmethod
    def _fetch(connection, uids: list[int]) -> list[tuple[int, bytes]]:
        """Fetch messages in order. A refused fetch ends the batch, never becomes b"".

        Messages before the refused one are still returned so they are not delayed;
        the refused UID is the first one of the next batch and raises FetchRejected.
        """
        messages = []
        for uid in uids:
            status, parts = connection.uid("FETCH", str(uid), "(BODY.PEEK[])")
            raw = next((p[1] for p in parts or [] if isinstance(p, tuple) and p[1]), None)
            if status != "OK" or raw is None:
                if messages:
                    break
                raise FetchRejected(uid)
            messages.append((uid, raw))
        return messages

    @staticmethod
    def is_valid_address(address: str) -> bool:
        return bool(ADDRESS_PATTERN.match(address))


class EmailSource:
    """Read the subject and build a Gmail link to the original message."""

    def __init__(self, raw: bytes) -> None:
        try:
            headers = BytesParser(policy=policy.default).parsebytes(raw, headersonly=True)
            self.subject = " ".join(str(headers.get("Subject") or "").split())
            self._message_id = str(headers.get("Message-ID") or "").strip().strip("<>")
        except Exception:  # A malformed header only means no subject or link.
            self.subject, self._message_id = "", ""

    def gmail_url(self, address: str) -> str | None:
        """Return a link that opens the message in that Gmail account, if it has an ID."""
        if not self._message_id:
            return None
        query = quote(f"rfc822msgid:{self._message_id}", safe="")
        return f"https://mail.google.com/mail/?authuser={quote(address, safe='')}#search/{query}"
