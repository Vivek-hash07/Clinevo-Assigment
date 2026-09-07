"""Mail intake: connection state, manual sync, IMAP setup, and synthetic seeding."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.config import get_settings
from app.deps import CurrentUser, DbSession
from app.jobqueue import store as queue_store
from app.jobqueue.handlers import KIND_MAIL_SYNC
from app.jobqueue.types import JobEvent
from app.models import GmailCredential, ImapAccount
from app.schemas import (
    ImapConnectRequest,
    ImapTestOut,
    MailProviderOut,
    MailStatusOut,
    MessageOut,
    SeedSyntheticOut,
    SyncMailOut,
)
from app.security import encrypt_secret
from app.services.audit import write_audit
from app.services.imap_client import (
    ImapSettings,
    normalize_app_password,
    suggest_host,
    verify_credentials,
)
from app.services.mail_errors import MailAuthError, MailProviderError
from app.services.mail_providers import PROVIDER_GMAIL, PROVIDER_IMAP
from app.services.mailboxes import list_syncable_mailboxes, mailbox_summary
from app.services.synthetic import batch_keys, send_synthetic_mailbox, synthetic_catalog

router = APIRouter(prefix="/api/mail", tags=["mail"])
# Old Angular builds still POST here. Keep the aliases so sync/seed do not 404.
gmail_compat = APIRouter(prefix="/api/gmail", tags=["gmail-compat"], include_in_schema=False)
logger = logging.getLogger(__name__)


def _iso(value) -> str | None:
    return value.isoformat() if value else None


@router.get("/status", response_model=MailStatusOut)
def mail_status(user: CurrentUser, db: DbSession) -> MailStatusOut:
    rows = mailbox_summary(db, user)
    providers = [
        MailProviderOut(
            provider=row["provider"],
            label=row["label"],
            connected=row["connected"],
            sync_enabled=row["sync_enabled"],
            email=row["email"],
            last_synced_at=_iso(row["last_synced_at"]),
            last_error=row["last_error"],
            host=row.get("host"),
            port=row.get("port"),
            folder=row.get("folder"),
        )
        for row in rows
    ]
    return MailStatusOut(
        connected=any(item.connected and item.sync_enabled for item in providers),
        providers=providers,
    )


@router.post("/sync", response_model=SyncMailOut)
def sync_mail(user: CurrentUser) -> SyncMailOut:
    """Poll every mailbox this user has connected, whichever provider it uses."""
    mailboxes = list_syncable_mailboxes(only_user_id=str(user.id))
    if not mailboxes:
        return SyncMailOut(
            ok=False,
            queued=False,
            mail_connected=False,
            message="Connect a mailbox first — sign in with Google or add an IMAP app password.",
        )
    event_ids = queue_store.enqueue(
        JobEvent(
            kind=KIND_MAIL_SYNC,
            payload={"user_id": str(user.id), "trigger": "manual"},
            idempotency_key=f"mail-sync-manual-{user.id}",
            user_id=str(user.id),
            max_attempts=2,
            # Ahead of background work so a reviewer pressing "Sync" is not stuck behind a batch.
            priority=10,
        )
    )
    providers = sorted({box.provider for box in mailboxes})
    if not event_ids:
        return SyncMailOut(
            ok=True,
            queued=False,
            mail_connected=True,
            providers=providers,
            message="A sync is already running for this mailbox. New messages will appear shortly.",
        )
    return SyncMailOut(
        ok=True,
        queued=True,
        mail_connected=True,
        providers=providers,
        queued_event_ids=event_ids,
        message=(
            f"Mailbox sync queued ({', '.join(providers)}). "
            "New messages will appear in the reviewer queue."
        ),
    )


# ------------------------------------------------------------------------------- IMAP


def _imap_settings_from(payload: ImapConnectRequest) -> ImapSettings:
    settings = get_settings()
    password = normalize_app_password(payload.app_password)
    if not password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Enter the app password.",
        )
    host = (payload.host or "").strip() or suggest_host(str(payload.email))
    return ImapSettings(
        email=str(payload.email),
        password=password,
        host=host,
        port=payload.port or settings.imap_default_port,
        use_ssl=payload.use_ssl,
        folder=(payload.folder or "").strip() or settings.imap_default_folder,
    )


def _verify_or_400(cfg: ImapSettings) -> dict:
    try:
        return verify_credentials(cfg)
    except MailAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except MailProviderError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=exc.detail) from exc
    except Exception as exc:
        logger.exception("IMAP verification failed for %s", cfg.host)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Could not complete the IMAP check against {cfg.host}.",
        ) from exc


@router.post("/imap/test", response_model=ImapTestOut)
def imap_test(payload: ImapConnectRequest, user: CurrentUser) -> ImapTestOut:
    """Log in and open the folder without storing anything, so setup errors are visible
    before the credential is saved."""
    cfg = _imap_settings_from(payload)
    result = _verify_or_400(cfg)
    return ImapTestOut(
        ok=True,
        host=cfg.host,
        port=cfg.port,
        folder=cfg.folder,
        message_count=int(result.get("message_count") or 0),
        message=(
            f"Connected to {cfg.host} as {cfg.email}. "
            f"{result.get('message_count', 0)} message(s) in {cfg.folder}."
        ),
    )


@router.post("/imap/connect", response_model=ImapTestOut)
def imap_connect(payload: ImapConnectRequest, user: CurrentUser, db: DbSession) -> ImapTestOut:
    cfg = _imap_settings_from(payload)
    result = _verify_or_400(cfg)

    account = db.scalar(select(ImapAccount).where(ImapAccount.user_id == user.id))
    if account is None:
        account = ImapAccount(user_id=user.id)
        db.add(account)
    account.email = cfg.email
    account.host = cfg.host
    account.port = cfg.port
    account.use_ssl = cfg.use_ssl
    account.folder = cfg.folder
    account.password_encrypted = encrypt_secret(cfg.password)
    account.sync_enabled = True
    account.last_error = None
    # Start from the newest messages rather than replaying the whole mailbox.
    account.uid_validity = str(result.get("uid_validity") or "0")
    account.last_uid = None
    write_audit(
        db,
        "mail.imap_connected",
        user.id,
        {"email": cfg.email, "host": cfg.host, "port": cfg.port, "folder": cfg.folder},
    )
    db.commit()

    queue_store.enqueue(
        JobEvent(
            kind=KIND_MAIL_SYNC,
            payload={"user_id": str(user.id), "trigger": "imap_connect"},
            idempotency_key=f"mail-sync-manual-{user.id}",
            user_id=str(user.id),
            max_attempts=2,
            priority=10,
        )
    )
    return ImapTestOut(
        ok=True,
        host=cfg.host,
        port=cfg.port,
        folder=cfg.folder,
        message_count=int(result.get("message_count") or 0),
        message=(
            f"IMAP mailbox {cfg.email} connected and the first sync is queued. "
            "The app password is encrypted at rest and only used to read mail."
        ),
    )


@router.post("/gmail/disconnect", response_model=MessageOut)
def gmail_disconnect(user: CurrentUser, db: DbSession) -> MessageOut:
    cred = db.scalar(select(GmailCredential).where(GmailCredential.user_id == user.id))
    if cred is None:
        return MessageOut(ok=True, message="No Gmail mailbox was connected.")
    email = cred.gmail_email
    db.delete(cred)
    write_audit(db, "mail.gmail_disconnected", user.id, {"email": email})
    db.commit()
    return MessageOut(
        ok=True,
        message=f"Disconnected Gmail{f' ({email})' if email else ''} and deleted the stored tokens.",
    )


@router.post("/imap/disconnect", response_model=MessageOut)
def imap_disconnect(user: CurrentUser, db: DbSession) -> MessageOut:
    account = db.scalar(select(ImapAccount).where(ImapAccount.user_id == user.id))
    if account is None:
        return MessageOut(ok=True, message="No IMAP mailbox was connected.")
    email = account.email
    db.delete(account)
    write_audit(db, "mail.imap_disconnected", user.id, {"email": email})
    db.commit()
    return MessageOut(
        ok=True,
        message=f"Disconnected {email} and deleted the stored app password.",
    )


# -------------------------------------------------------------------- synthetic seeding


@router.post("/seed", response_model=SeedSyntheticOut)
def seed_synthetic(user: CurrentUser, db: DbSession) -> SeedSyntheticOut:
    """Send the synthetic batch to the connected mailbox over SMTP, so the full
    mail-intake path (not just the local fixture loader) is exercised."""
    rows = {row["provider"]: row for row in mailbox_summary(db, user)}
    mailbox = None
    for provider in (PROVIDER_IMAP, PROVIDER_GMAIL):
        row = rows.get(provider)
        if row and row["connected"] and row["sync_enabled"]:
            mailbox = row["email"]
            break
    mailbox = mailbox or user.email
    if not mailbox:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect a mailbox before sending sample mail.",
        )
    try:
        result = send_synthetic_mailbox(mailbox, batch_keys())
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "SMTP is not configured, so sample mail cannot be sent. "
                "Use \"Load local fixtures\" to put the same documents in the queue without email."
            ),
        ) from exc
    except Exception:
        logger.exception("Synthetic mailbox send failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send sample emails. Check SMTP settings and try again.",
        ) from None
    write_audit(
        db,
        "mail.synthetic_seeded",
        user.id,
        {"to": mailbox, "templates": result["sent"]},
    )
    db.commit()
    return SeedSyntheticOut(
        ok=True,
        to=mailbox,
        count=result["count"],
        sent=result["sent"],
        message=(
            f"Sent {result['count']} synthetic emails to {mailbox} (Day 6 batch). "
            "Wait about 15 seconds, then sync the mailbox."
        ),
    )


@router.get("/seed/templates")
def seed_templates(user: CurrentUser) -> dict:
    return {"templates": [item.key for item in synthetic_catalog()]}


@gmail_compat.post("/sync", response_model=SyncMailOut)
def sync_mail_compat(user: CurrentUser) -> SyncMailOut:
    return sync_mail(user)


@gmail_compat.post("/seed", response_model=SeedSyntheticOut)
def seed_synthetic_compat(user: CurrentUser, db: DbSession) -> SeedSyntheticOut:
    return seed_synthetic(user, db)
