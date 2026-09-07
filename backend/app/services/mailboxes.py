"""Which mailboxes are connected, and what state each one is in."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import GmailCredential, ImapAccount, User
from app.services.mail_providers import PROVIDER_GMAIL, PROVIDER_IMAP


@dataclass
class Mailbox:
    user_id: str
    provider: str
    email: str | None
    sync_enabled: bool
    cursor: str | None = None
    last_synced_at: datetime | None = None
    last_error: str | None = None


def list_syncable_mailboxes(only_user_id: str | None = None) -> list[Mailbox]:
    """Every mailbox the scheduler should poll: connected, enabled, with a usable secret."""
    from app.database import session_scope

    with session_scope() as db:
        boxes: list[Mailbox] = []

        gmail_stmt = select(GmailCredential).where(
            GmailCredential.sync_enabled.is_(True),
            GmailCredential.refresh_token_encrypted.is_not(None),
        )
        if only_user_id:
            gmail_stmt = gmail_stmt.where(GmailCredential.user_id == only_user_id)
        for cred in db.scalars(gmail_stmt).all():
            boxes.append(
                Mailbox(
                    user_id=cred.user_id,
                    provider=PROVIDER_GMAIL,
                    email=cred.gmail_email,
                    sync_enabled=True,
                    cursor=cred.history_id,
                    last_synced_at=cred.last_synced_at,
                    last_error=cred.last_error,
                )
            )

        imap_stmt = select(ImapAccount).where(
            ImapAccount.sync_enabled.is_(True),
            ImapAccount.password_encrypted.is_not(None),
        )
        if only_user_id:
            imap_stmt = imap_stmt.where(ImapAccount.user_id == only_user_id)
        for account in db.scalars(imap_stmt).all():
            boxes.append(
                Mailbox(
                    user_id=account.user_id,
                    provider=PROVIDER_IMAP,
                    email=account.email,
                    sync_enabled=True,
                    cursor=_imap_cursor(account),
                    last_synced_at=account.last_synced_at,
                    last_error=account.last_error,
                )
            )
        return boxes


def _imap_cursor(account: ImapAccount) -> str | None:
    if account.last_uid is None:
        return None
    return f"{account.uid_validity or '0'}:{account.last_uid}"


def read_cursor(db: Session, user_id: str, provider: str) -> str | None:
    if provider == PROVIDER_GMAIL:
        cred = db.scalar(select(GmailCredential).where(GmailCredential.user_id == user_id))
        return cred.history_id if cred else None
    account = db.scalar(select(ImapAccount).where(ImapAccount.user_id == user_id))
    return _imap_cursor(account) if account else None


def mailbox_summary(db: Session, user: User) -> list[dict]:
    """Per-provider connection state for the reviewer UI."""
    rows: list[dict] = []
    cred = db.scalar(select(GmailCredential).where(GmailCredential.user_id == user.id))
    rows.append(
        {
            "provider": PROVIDER_GMAIL,
            "label": "Google (OAuth)",
            "connected": bool(cred and cred.refresh_token_encrypted),
            "sync_enabled": bool(cred and cred.sync_enabled),
            "email": cred.gmail_email if cred else None,
            "last_synced_at": cred.last_synced_at if cred else None,
            "last_error": cred.last_error if cred else None,
            "cursor": cred.history_id if cred else None,
        }
    )
    account = db.scalar(select(ImapAccount).where(ImapAccount.user_id == user.id))
    rows.append(
        {
            "provider": PROVIDER_IMAP,
            "label": "IMAP (app password)",
            "connected": bool(account and account.password_encrypted),
            "sync_enabled": bool(account and account.sync_enabled),
            "email": account.email if account else None,
            "last_synced_at": account.last_synced_at if account else None,
            "last_error": account.last_error if account else None,
            "cursor": _imap_cursor(account) if account else None,
            "host": account.host if account else None,
            "port": account.port if account else None,
            "folder": account.folder if account else None,
        }
    )
    return rows
