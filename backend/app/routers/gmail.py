from __future__ import annotations

import logging
import time

import inngest
from fastapi import APIRouter, HTTPException, status

from app.deps import CurrentUser, DbSession
from app.inngest_client import inngest_client
from app.models import GmailCredential
from app.schemas import GmailStatusOut, SeedSyntheticOut, SyncMailOut
from app.services.audit import write_audit
from app.services.synthetic import batch_keys, send_synthetic_mailbox, synthetic_catalog

router = APIRouter(prefix="/api/gmail", tags=["gmail"])
logger = logging.getLogger(__name__)


def _credential(user) -> GmailCredential | None:
    return user.gmail_credential


def _connected(cred: GmailCredential | None) -> bool:
    return bool(cred and cred.refresh_token_encrypted and cred.sync_enabled)


@router.get("/status", response_model=GmailStatusOut)
def gmail_status(user: CurrentUser) -> GmailStatusOut:
    cred = _credential(user)
    return GmailStatusOut(
        connected=_connected(cred),
        sync_enabled=bool(cred.sync_enabled) if cred else False,
        gmail_email=cred.gmail_email if cred else None,
        last_synced_at=cred.last_synced_at.isoformat() if cred and cred.last_synced_at else None,
        last_error=cred.last_error if cred else None,
    )


@router.post("/sync", response_model=SyncMailOut)
def sync_mail(user: CurrentUser) -> SyncMailOut:
    cred = _credential(user)
    if not _connected(cred):
        return SyncMailOut(
            ok=False,
            queued=False,
            gmail_connected=False,
            message="Connect your Google mailbox to sync mail.",
        )
    try:
        ids = inngest_client.send_sync(
            inngest.Event(
                name="gmail/sync.mailbox",
                id=f"gmail-sync-mailbox-{user.id}-{int(time.time()) // 15}",
                data={"user_id": str(user.id)},
            )
        )
    except Exception:
        logger.exception("Failed to enqueue gmail sync")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Mail sync could not be queued. Start the Inngest Dev Server "
                "(npx inngest-cli@latest dev -u http://localhost:8080/api/inngest) and try again."
            ),
        ) from None
    return SyncMailOut(
        ok=True,
        queued=True,
        gmail_connected=True,
        queued_event_ids=list(ids or []),
        message="Mailbox sync queued. New messages will appear in the reviewer queue.",
    )


@router.post("/seed", response_model=SeedSyntheticOut)
def seed_synthetic(user: CurrentUser, db: DbSession) -> SeedSyntheticOut:
    cred = _credential(user)
    if not _connected(cred):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Connect your Google mailbox before sending sample mail.",
        )
    mailbox = (cred.gmail_email if cred else None) or user.email
    try:
        result = send_synthetic_mailbox(mailbox, batch_keys())
    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="SMTP is not configured, so sample mail cannot be sent.",
        ) from exc
    except Exception:
        logger.exception("Synthetic mailbox send failed")
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Could not send sample emails. Check SMTP settings and try again.",
        ) from None
    write_audit(
        db,
        "gmail.synthetic_seeded",
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
