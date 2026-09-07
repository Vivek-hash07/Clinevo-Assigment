"""One interface over the two ways mail enters the app.

`gmail`  — Google OAuth + Gmail REST API. Restricted scope, so an unverified app is
           limited to test users, but it needs no password and supports incremental
           history sync.
`imap`   — IMAP + app password. No Google review needed and works with any provider;
           the cursor is the mailbox UID.
"""

from __future__ import annotations

import logging
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings, get_settings
from app.models import GmailCredential, ImapAccount
from app.security import decrypt_secret
from app.services.gmail_client import GmailClient
from app.services.gmail_parse import parse_gmail_message
from app.services.imap_client import DEFAULT_FOLDER, ImapMailbox, ImapSettings
from app.services.mail_errors import MailAuthError, MailCursorExpired, MailProviderError
from app.services.mail_types import ParsedAttachment, ParsedMessage
from app.services.rfc822_parse import parse_rfc822

logger = logging.getLogger(__name__)

PROVIDER_GMAIL = "gmail"
PROVIDER_IMAP = "imap"
MAIL_PROVIDERS = (PROVIDER_GMAIL, PROVIDER_IMAP)


class MailProvider(Protocol):
    provider: str
    email: str | None

    def list_new_message_ids(self, cursor: str | None, limit: int) -> tuple[list[str], str | None]:
        """Return (provider message ids, new cursor). Ids are safe to persist."""

    def fetch_message(self, provider_message_id: str) -> ParsedMessage: ...

    def fetch_attachment(self, provider_message_id: str, part: ParsedAttachment) -> bytes: ...

    def close(self) -> None: ...


class GmailProvider:
    provider = PROVIDER_GMAIL

    def __init__(self, db: Session, cred: GmailCredential, settings: Settings | None = None) -> None:
        self._client = GmailClient(db, cred, settings or get_settings())
        self.email = cred.gmail_email

    def list_new_message_ids(self, cursor: str | None, limit: int) -> tuple[list[str], str | None]:
        if cursor:
            try:
                ids, history_id = self._client.list_history_ids(cursor)
            except MailCursorExpired:
                ids, history_id = self._client.list_inbox_ids()
        else:
            ids, history_id = self._client.list_inbox_ids()
        return ids[:limit] if limit > 0 else ids, history_id

    def fetch_message(self, provider_message_id: str) -> ParsedMessage:
        return parse_gmail_message(self._client.get_message(provider_message_id))

    def fetch_attachment(self, provider_message_id: str, part: ParsedAttachment) -> bytes:
        if part.inline_data:
            return part.inline_data
        if part.attachment_id:
            return self._client.get_attachment_bytes(provider_message_id, part.attachment_id)
        return b""

    def close(self) -> None:
        return None


class ImapProvider:
    """Message ids are "<uid_validity>:<uid>", which keeps them stable for as long as
    the server keeps the same UIDVALIDITY and invalidates them all if it does not."""

    provider = PROVIDER_IMAP

    def __init__(self, account: ImapAccount, password: str) -> None:
        self.email = account.email
        self._settings = ImapSettings(
            email=account.email,
            password=password,
            host=account.host,
            port=account.port,
            use_ssl=account.use_ssl,
            folder=account.folder or DEFAULT_FOLDER,
        )
        self._box: ImapMailbox | None = None
        self._uid_validity: str | None = None

    def _mailbox(self) -> ImapMailbox:
        if self._box is None:
            box = ImapMailbox(self._settings)
            box.connect()
            state = box.select_folder(readonly=True)
            self._uid_validity = state.uid_validity
            self._box = box
        return self._box

    def list_new_message_ids(self, cursor: str | None, limit: int) -> tuple[list[str], str | None]:
        box = self._mailbox()
        validity = self._uid_validity or "0"
        previous_validity, last_uid = _split_imap_cursor(cursor)
        if previous_validity is not None and previous_validity != validity:
            # The server renumbered the folder; every stored UID is meaningless now.
            logger.info(
                "IMAP UIDVALIDITY changed for %s (%s -> %s); restarting from a bounded list",
                self.email,
                previous_validity,
                validity,
            )
            last_uid = None
        uids = box.list_uids_since(last_uid, limit) if last_uid else box.list_recent_uids(limit)
        highest = max(uids) if uids else last_uid
        cursor_out = f"{validity}:{highest}" if highest else f"{validity}:0"
        return [f"{validity}:{uid}" for uid in uids], cursor_out

    def fetch_message(self, provider_message_id: str) -> ParsedMessage:
        box = self._mailbox()
        validity, uid = _split_imap_cursor(provider_message_id)
        if uid is None:
            raise MailProviderError(400, f"Malformed IMAP message id {provider_message_id!r}")
        if validity is not None and self._uid_validity and validity != self._uid_validity:
            raise MailCursorExpired(
                f"UID {uid} belongs to an older UIDVALIDITY generation ({validity})"
            )
        raw = box.fetch_rfc822(uid)
        return parse_rfc822(raw, provider_message_id, in_inbox=True)

    def fetch_attachment(self, provider_message_id: str, part: ParsedAttachment) -> bytes:
        # IMAP FETCH already returned the whole MIME tree.
        return part.inline_data or b""

    def close(self) -> None:
        if self._box is not None:
            self._box.close()
            self._box = None


def _split_imap_cursor(value: str | None) -> tuple[str | None, int | None]:
    if not value:
        return None, None
    text = str(value)
    if ":" in text:
        validity, _, uid = text.rpartition(":")
        return (validity or None), (int(uid) if uid.isdigit() else None)
    return None, (int(text) if text.isdigit() else None)


def open_provider(db: Session, user_id: str, provider: str) -> MailProvider:
    """Build a live provider for a connected mailbox, or raise MailAuthError."""
    if provider == PROVIDER_GMAIL:
        cred = db.scalar(select(GmailCredential).where(GmailCredential.user_id == user_id))
        if cred is None or not cred.refresh_token_encrypted or not cred.sync_enabled:
            raise MailAuthError("Google mailbox is not connected.")
        return GmailProvider(db, cred)

    if provider == PROVIDER_IMAP:
        account = db.scalar(select(ImapAccount).where(ImapAccount.user_id == user_id))
        if account is None or not account.password_encrypted or not account.sync_enabled:
            raise MailAuthError("IMAP mailbox is not connected.")
        try:
            password = decrypt_secret(account.password_encrypted)
        except ValueError as exc:
            account.sync_enabled = False
            account.last_error = "Stored app password could not be decrypted. Reconnect the mailbox."
            raise MailAuthError(account.last_error) from exc
        return ImapProvider(account, password)

    raise MailProviderError(400, f"Unknown mail provider {provider!r}")
